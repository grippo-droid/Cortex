"""Chat routes: session management over HTTP, and the streaming socket."""

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from sqlalchemy.orm import Session

from app.api.deps import authenticate_websocket, get_current_user
from app.database import SessionLocal, get_db
from app.models import User
from app.schemas.chat import ChatSessionCreate, ChatSessionRead, MessageRead
from app.services import chat_service

router = APIRouter(prefix="/chat", tags=["chat"])

SESSION_NOT_FOUND_DETAIL = "Chat session not found."

# One reason for every refusal. A caller must not be able to tell a bad token
# from a session that is not theirs from a session that does not exist.
WS_REJECT_REASON = "Unauthorised."


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
            await websocket.receive_text()

            # Retrieval (T3.3), augmentation (T3.4), and generation (T3.5)
            # replace this. Answering with an explicit error is better than
            # silently discarding the question. `authorised_user_id` is what
            # scopes retrieval to this caller's own collection.
            await websocket.send_json(
                {
                    "type": "error",
                    "detail": "Answer generation is not implemented yet.",
                }
            )
    except WebSocketDisconnect:
        return
