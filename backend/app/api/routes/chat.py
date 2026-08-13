"""Chat routes: session management over HTTP, and the streaming socket."""

import asyncio
from dataclasses import dataclass

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.concurrency import run_in_threadpool
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.deps import authenticate_websocket, get_current_user
from app.database import SessionLocal, get_db
from app.models import MessageRole, User
from app.schemas.chat import (
    ChatQuestion,
    ChatSessionCreate,
    ChatSessionRead,
    MessageRead,
)
from app.config import settings
from app.services import chat_service, document_service, llm, prompting, retrieval
from app.services.embeddings import EmbeddingError

router = APIRouter(prefix="/chat", tags=["chat"])

SESSION_NOT_FOUND_DETAIL = "Chat session not found."

# One reason for every refusal. A caller must not be able to tell a bad token
# from a session that is not theirs from a session that does not exist.
WS_REJECT_REASON = "Unauthorised."


_STREAM_END = object()


async def _stream_answer(
    websocket: WebSocket, messages: list[dict[str, str]]
) -> tuple[str, str | None]:
    """Stream a completion to the socket. Returns (text so far, error or None).

    The provider's stream is a synchronous generator. Iterating it directly in
    this coroutine would block the event loop between every token, stalling
    every other connected socket for the length of the answer.
    `run_in_threadpool` does not solve that either: it awaits one call, whereas
    this yields repeatedly over several seconds.

    So the generator runs on a worker thread and hands fragments back through an
    asyncio queue, which this coroutine drains. The event loop stays free
    throughout, and two people can chat at the same time without either waiting
    on the other.
    """
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def produce() -> None:
        try:
            for fragment in llm.stream_completion(messages):
                loop.call_soon_threadsafe(queue.put_nowait, fragment)
        except Exception as exc:  # surfaced to the client below
            loop.call_soon_threadsafe(queue.put_nowait, exc)
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, _STREAM_END)

    loop.run_in_executor(None, produce)

    parts: list[str] = []
    error: str | None = None
    deadline = loop.time() + settings.llm_stream_timeout_seconds

    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            error = "The model took too long to respond."
            break

        try:
            item = await asyncio.wait_for(queue.get(), timeout=remaining)
        except TimeoutError:
            error = "The model took too long to respond."
            break

        if item is _STREAM_END:
            break

        if isinstance(item, Exception):
            error = str(item)
            continue  # the sentinel follows, ending the loop

        parts.append(item)
        await websocket.send_json({"type": "token", "content": item})

    return "".join(parts), error


@dataclass(frozen=True)
class _HistoryTurn:
    """A detached copy of a stored message.

    Copied out while the database session is open so prompt assembly never
    touches an expired ORM instance after the session has closed.
    """

    role: str
    content: str


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail=SESSION_NOT_FOUND_DETAIL
    )


@router.post(
    "/sessions", response_model=ChatSessionRead, status_code=status.HTTP_201_CREATED
)
def create_session(
    payload: ChatSessionCreate | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ChatSessionRead:
    session = chat_service.create_session(
        db, user_id=current_user.id, title=payload.title if payload else None
    )
    return ChatSessionRead.model_validate(session)


@router.get("/sessions", response_model=list[ChatSessionRead])
def list_sessions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ChatSessionRead]:
    sessions = chat_service.list_sessions(db, user_id=current_user.id)
    return [ChatSessionRead.model_validate(session) for session in sessions]


@router.get("/sessions/{session_id}", response_model=ChatSessionRead)
def read_session(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ChatSessionRead:
    try:
        session = chat_service.get_session(
            db, user_id=current_user.id, session_id=session_id
        )
    except chat_service.ChatSessionNotFoundError:
        raise _not_found() from None

    return ChatSessionRead.model_validate(session)


@router.get("/sessions/{session_id}/messages", response_model=list[MessageRead])
def read_session_messages(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[MessageRead]:
    """History for one session. The frontend re-fetches this after a WS reconnect."""
    try:
        messages = chat_service.list_messages(
            db, user_id=current_user.id, session_id=session_id
        )
    except chat_service.ChatSessionNotFoundError:
        raise _not_found() from None

    return [MessageRead.model_validate(message) for message in messages]


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    try:
        chat_service.delete_session(
            db, user_id=current_user.id, session_id=session_id
        )
    except chat_service.ChatSessionNotFoundError:
        raise _not_found() from None


@router.websocket("/stream/{session_id}")
async def chat_stream(websocket: WebSocket, session_id: int) -> None:
    """Streaming chat socket.

    The client's first frame must be {"type": "auth", "token": "<jwt>"}. Nothing
    is sent to the socket until that token has been verified and the session
    confirmed to belong to its bearer.
    """
    await websocket.accept()

    # A short-lived session rather than Depends(get_db): that would keep a
    # database connection checked out for as long as the tab stays open, and
    # risks serving identity-map data that went stale hours ago.
    with SessionLocal() as db:
        user = await authenticate_websocket(websocket, db)

        if user is None:
            await websocket.close(
                code=status.WS_1008_POLICY_VIOLATION, reason=WS_REJECT_REASON
            )
            return

        try:
            session = chat_service.get_session(
                db, user_id=user.id, session_id=session_id
            )
        except chat_service.ChatSessionNotFoundError:
            # Deliberately identical to the failure above.
            await websocket.close(
                code=status.WS_1008_POLICY_VIOLATION, reason=WS_REJECT_REASON
            )
            return

        # Read while the instances are still attached to the session.
        authorised_user_id = user.id
        authorised_session_id = session.id

    await websocket.send_json({"type": "ready", "session_id": authorised_session_id})

    try:
        while True:
            raw = await websocket.receive_text()

            try:
                question = ChatQuestion.model_validate_json(raw)
            except ValidationError:
                await websocket.send_json(
                    {
                        "type": "error",
                        "detail": "Expected a message frame with content.",
                    }
                )
                continue

            try:
                # Embedding and the Chroma query both block. Running them inline
                # would stall the event loop, freezing every other connected
                # socket for the duration.
                #
                # `authorised_user_id` came from the handshake token. Nothing in
                # `question` influences which collection is searched, which is
                # what stops a client smuggling someone else's id in the frame.
                chunks = await run_in_threadpool(
                    retrieval.retrieve_context, authorised_user_id, question.content
                )
            except EmbeddingError as exc:
                await websocket.send_json(
                    {
                        "type": "error",
                        "detail": f"Could not embed the question: {exc}",
                    }
                )
                continue

            await websocket.send_json(
                {
                    "type": "sources",
                    "chunks": [
                        {
                            "content": chunk.content,
                            "filename": chunk.filename,
                            "document_id": chunk.document_id,
                            "chunk_index": chunk.chunk_index,
                            "distance": chunk.distance,
                        }
                        for chunk in chunks
                    ],
                }
            )

            try:
                with SessionLocal() as db:
                    # Read the prior turns before storing this question, so the
                    # current one is not both in the history and in the final
                    # user message.
                    history = chat_service.list_messages(
                        db,
                        user_id=authorised_user_id,
                        session_id=authorised_session_id,
                    )
                    turns = [
                        _HistoryTurn(role=message.role, content=message.content)
                        for message in history
                    ]

                    # Stored before generation: if the provider fails mid-answer
                    # the question still belongs in the transcript, rather than
                    # disappearing on the next refresh.
                    chat_service.add_message(
                        db,
                        user_id=authorised_user_id,
                        session_id=authorised_session_id,
                        role=MessageRole.USER,
                        content=question.content,
                    )

                    has_documents = (
                        document_service.count_documents(db, authorised_user_id) > 0
                    )
            except chat_service.ChatSessionNotFoundError:
                # Deleted from another tab while this socket was open.
                await websocket.send_json(
                    {"type": "error", "detail": "This chat session no longer exists."}
                )
                break

            if not chunks:
                # Nothing retrieved: answer directly rather than paying for a
                # model call to be told what we already know.
                reply = prompting.no_context_reply(has_documents)

                with SessionLocal() as db:
                    chat_service.add_message(
                        db,
                        user_id=authorised_user_id,
                        session_id=authorised_session_id,
                        role=MessageRole.ASSISTANT,
                        content=reply,
                    )

                await websocket.send_json(
                    {"type": "answer", "content": reply, "done": True}
                )
                continue

            messages = prompting.build_chat_messages(question.content, chunks, turns)

            # Lets the client swap its typing indicator for an empty assistant
            # bubble before the first token lands.
            await websocket.send_json({"type": "start"})

            answer, error = await _stream_answer(websocket, messages)

            if error is not None:
                await websocket.send_json({"type": "error", "detail": error})

            if error is None or answer:
                # `done` repeats the whole answer so the client can reconcile
                # rather than trusting its own concatenation of the tokens. A
                # partial answer is still sent, marked as incomplete, so the
                # user keeps what did arrive instead of watching it vanish.
                await websocket.send_json(
                    {
                        "type": "done",
                        "content": answer,
                        "partial": error is not None,
                    }
                )

            if answer:
                # Stored once at the end rather than per token. A partial answer
                # is kept, because the user read it, but marked so the record
                # does not present it as finished and the next turn's history
                # does not treat it as a complete reply.
                stored = (
                    answer + chat_service.INCOMPLETE_ANSWER_SUFFIX
                    if error is not None
                    else answer
                )

                with SessionLocal() as db:
                    chat_service.add_message(
                        db,
                        user_id=authorised_user_id,
                        session_id=authorised_session_id,
                        role=MessageRole.ASSISTANT,
                        content=stored,
                    )
            # Nothing generated: the question stands alone until it is retried.
    except WebSocketDisconnect:
        return
