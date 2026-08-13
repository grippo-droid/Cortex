"""Chat routes. The WebSocket stream lands in T3.2."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.database import get_db
from app.models import User
from app.schemas.chat import ChatSessionCreate, ChatSessionRead, MessageRead
from app.services import chat_service

router = APIRouter(prefix="/chat", tags=["chat"])

SESSION_NOT_FOUND_DETAIL = "Chat session not found."


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
