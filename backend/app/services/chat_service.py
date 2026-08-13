"""Chat session business logic.

`get_session` is the single ownership gate for everything session-scoped. The
WebSocket handler in T3.2 must authorise through it too rather than writing its
own query, so that the rule lives in exactly one place.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ChatSession, Message

DEFAULT_SESSION_TITLE = "New chat"

# Appended to an answer whose stream failed part way through. The user read that
# text, so the transcript keeps it, but the record should not present a
# truncated answer as a finished one.
INCOMPLETE_ANSWER_SUFFIX = (
    "\n\n_[Answer incomplete: the connection to the model failed.]_"
)


class ChatSessionNotFoundError(Exception):
    """No such session for this user. Also raised when it belongs to someone else."""


def create_session(db: Session, user_id: int, title: str | None = None) -> ChatSession:
    session = ChatSession(user_id=user_id, title=title or DEFAULT_SESSION_TITLE)

    db.add(session)
    db.commit()
    db.refresh(session)

    return session


def list_sessions(db: Session, user_id: int) -> list[ChatSession]:
    return list(
        db.scalars(
            select(ChatSession)
            .where(ChatSession.user_id == user_id)
            .order_by(ChatSession.created_at.desc(), ChatSession.id.desc())
        )
    )


def get_session(db: Session, user_id: int, session_id: int) -> ChatSession:
    """Fetch one session, scoped to its owner.

    The user_id predicate is what makes a session id taken from a URL safe to
    act on. A missing session and someone else's session raise the same error,
    so the endpoints above cannot be used to discover which ids exist.
    """
    session = db.scalar(
        select(ChatSession).where(
            ChatSession.id == session_id, ChatSession.user_id == user_id
        )
    )

    if session is None:
        raise ChatSessionNotFoundError(str(session_id))

    return session


def list_messages(db: Session, user_id: int, session_id: int) -> list[Message]:
    """Messages in one session, oldest first. Ownership is checked first."""
    session = get_session(db, user_id, session_id)

    return list(
        db.scalars(
            select(Message)
            .where(Message.session_id == session.id)
            .order_by(Message.created_at, Message.id)
        )
    )


def add_message(
    db: Session, user_id: int, session_id: int, role: str, content: str
) -> Message:
    """Append a message to a session the caller owns.

    Ownership is re-checked rather than assumed. The socket authorised once at
    connect, but a session can be deleted from another tab while a connection is
    open, and writing to a session row that no longer exists would otherwise
    fail on the foreign key as an unhandled error.
    """
    session = get_session(db, user_id, session_id)

    message = Message(session_id=session.id, role=role, content=content)
    db.add(message)
    db.commit()
    db.refresh(message)

    return message


def delete_session(db: Session, user_id: int, session_id: int) -> None:
    """Delete a session and, by cascade, its messages.

    Unlike documents this touches no vectors: chat history lives only in the
    relational database.
    """
    session = get_session(db, user_id, session_id)

    db.delete(session)
    db.commit()
