"""Authentication business logic, kept out of the route layer."""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import DUMMY_PASSWORD_HASH, hash_password, verify_password
from app.models import User


class EmailAlreadyRegisteredError(Exception):
    """Raised when an email address already belongs to an account."""


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == email))


def register_user(db: Session, email: str, password: str) -> User:
    """Create a user, storing only the bcrypt hash of their password."""
    if get_user_by_email(db, email) is not None:
        raise EmailAlreadyRegisteredError(email)

    user = User(email=email, hashed_password=hash_password(password))
    db.add(user)

    try:
        db.commit()
    except IntegrityError as exc:
        # Two concurrent registrations can both pass the check above. The UNIQUE
        # constraint on users.email is the guarantee; this is the race handler.
        db.rollback()
        raise EmailAlreadyRegisteredError(email) from exc

    db.refresh(user)
    return user


def authenticate_user(db: Session, email: str, password: str) -> User | None:
    """Return the user if the credentials are valid, otherwise None.

    Callers must not distinguish "no such account" from "wrong password" in the
    response — see the single 401 in the login route.
    """
    user = get_user_by_email(db, email)

    if user is None:
        # Burn a comparable amount of CPU so an unregistered address does not
        # answer measurably faster than a registered one.
        verify_password(password, DUMMY_PASSWORD_HASH)
        return None

    if not verify_password(password, user.hashed_password):
        return None

    return user
