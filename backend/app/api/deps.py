"""Shared route dependencies.

`get_current_user` is the only place a user id enters the application. Every
user-scoped query downstream must filter on the id it returns, and never on a
value taken from a path, query string, or request body — see
docs/03_Security_and_Access.md section 2.
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.database import get_db
from app.models import User

# auto_error=False so a missing Authorization header reaches our own handler.
# FastAPI's default would answer 403 for a missing header and 401 for a bad
# token; both are authentication failures and should look identical.
_bearer_scheme = HTTPBearer(auto_error=False)

# One message for every rejection. Distinguishing "expired" from "forged" from
# "no such user" would let a caller probe for valid tokens and live accounts.
CREDENTIALS_ERROR_DETAIL = "Could not validate credentials."


def _unauthorised() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=CREDENTIALS_ERROR_DETAIL,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Resolve the caller from their bearer token, or reject the request."""
    if credentials is None or not credentials.credentials:
        raise _unauthorised()

    try:
        claims = decode_access_token(credentials.credentials)
    except JWTError:
        raise _unauthorised() from None

    subject = claims.get("sub")
    if subject is None:
        raise _unauthorised()

    try:
        user_id = int(subject)
    except (TypeError, ValueError):
        raise _unauthorised() from None

    user = db.get(User, user_id)
    if user is None:
        # The signature is genuine but the account is gone, taking its documents
        # and chats with it. The token has to stop working immediately.
        raise _unauthorised()

    return user
