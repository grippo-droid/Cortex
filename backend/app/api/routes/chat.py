"""Chat routes: session management over HTTP, and the streaming socket."""

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
from app.models import User
from app.schemas.chat import (
    ChatQuestion,
    ChatSessionCreate,
    ChatSessionRead,
    MessageRead,
)
from app.services import chat_service, document_service, prompting, retrieval
from app.services.embeddings import EmbeddingError

router = APIRouter(prefix="/chat", tags=["chat"])

SESSION_NOT_FOUND_DETAIL = "Chat session not found."

# One reason for every refusal. A caller must not be able to tell a bad token
# from a session that is not theirs from a session that does not exist.
WS_REJECT_REASON = "Unauthorised."


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

            if not chunks:
                # Nothing retrieved: answer directly rather than paying for a
                # model call to be told what we already know.
                with SessionLocal() as db:
                    has_documents = (
                        document_service.count_documents(db, authorised_user_id) > 0
                    )

                await websocket.send_json(
                    {
                        "type": "answer",
                        "content": prompting.no_context_reply(has_documents),
                        "done": True,
                    }
                )
                continue

            with SessionLocal() as db:
                history = chat_service.list_messages(
                    db, user_id=authorised_user_id, session_id=authorised_session_id
                )
                turns = [
                    _HistoryTurn(role=message.role, content=message.content)
                    for message in history
                ]

            messages = prompting.build_chat_messages(question.content, chunks, turns)

            # Generation (T3.5) replaces this. Only the shape is reported: the
            # assembled prompt is not echoed to the client.
            await websocket.send_json(
                {
                    "type": "prompt_ready",
                    "message_count": len(messages),
                    "context_chunks": len(chunks),
                    "history_turns": len(messages) - 2,
                }
            )
    except WebSocketDisconnect:
        return
