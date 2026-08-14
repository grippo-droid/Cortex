"""Shared route dependencies.

`get_current_user` is the only place a user id enters the application. Every
user-scoped query downstream must filter on the id it returns, and never on a
value taken from a path, query string, or request body — see
docs/03_Security_and_Access.md section 2.
"""

import asyncio
import json

from fastapi import (
    Depends,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.database import get_db
from app.models import User
from app.observability import user_id_var

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
    request: Request,
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

    # Recorded for the request log only. Authorisation never reads it back; the
    # returned `user` remains the single source of identity downstream.
    #
    # Written to the request scope rather than only to the ContextVar because
    # FastAPI runs sync dependencies in a worker thread, which receives a copy
    # of the context, so a ContextVar set here would be invisible to the
    # middleware. The scope dict is shared, so it survives the hop.
    request.state.user_id = user.id
    user_id_var.set(user.id)
    return user


# How long an accepted socket may stay silent before it is closed. Without a
# bound, unauthenticated sockets could be opened and held open indefinitely.
AUTH_FRAME_TIMEOUT_SECONDS = 5.0


async def authenticate_websocket(websocket: WebSocket, db: Session) -> User | None:
    """Authenticate a WebSocket from its opening frame.

    A browser cannot set headers on a WebSocket handshake, so the token cannot
    travel in an Authorization header. The alternatives are a query parameter or
    an opening message; this takes the opening message, because a query string
    is written to server access logs, proxy logs, and browser history, and a
    token leaked there is a live session for the rest of its lifetime.

    The socket must be accepted before a frame can be read, so an
    unauthenticated socket does exist briefly. It is sent nothing and no session
    data is touched until the caller is known, and the caller closes it on any
    failure.

    Returns None for every failure mode, so the caller cannot accidentally
    report them differently and turn this into an oracle.
    """
    try:
        raw = await asyncio.wait_for(
            websocket.receive_text(), timeout=AUTH_FRAME_TIMEOUT_SECONDS
        )
    except (TimeoutError, WebSocketDisconnect):
        return None

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None

    if not isinstance(payload, dict) or payload.get("type") != "auth":
        return None

    token = payload.get("token")
    if not isinstance(token, str) or not token:
        return None

    try:
        claims = decode_access_token(token)
    except JWTError:
        return None

    try:
        user_id = int(claims.get("sub"))
    except (TypeError, ValueError):
        return None

    # A valid signature over a deleted account is still not a caller.
    user = db.get(User, user_id)
    if user is not None:
        # Logging only, as above.
        websocket.state.user_id = user.id
        user_id_var.set(user.id)
    return user
