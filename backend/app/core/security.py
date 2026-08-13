"""Password hashing, JWT creation, and JWT verification."""

from datetime import datetime, timedelta, timezone

from jose import jwt
from passlib.context import CryptContext

from app.config import settings

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Hash of a throwaway string, used to burn the same CPU on the "no such user"
# login path as on a real one. Without it, a missing account answers in about a
# millisecond and a real account in a few hundred, which tells an attacker which
# email addresses are registered.
DUMMY_PASSWORD_HASH = _pwd_context.hash("cortex-timing-equalisation-placeholder")


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return _pwd_context.verify(plain_password, hashed_password)


def create_access_token(
    subject: str | int, expires_delta: timedelta | None = None
) -> str:
    """Mint a signed JWT. `subject` becomes the `sub` claim, always as a string."""
    issued_at = datetime.now(timezone.utc)
    expires_at = issued_at + (
        expires_delta or timedelta(minutes=settings.jwt_expire_minutes)
    )

    payload = {
        # The JWT spec requires `sub` to be a string; some validators reject an
        # integer outright. T1.3 casts it back to int.
        "sub": str(subject),
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
    }

    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    """Verify a JWT and return its claims. Raises `JWTError` if it is not valid.

    `algorithms` is a strict allow-list rather than whatever the token's own
    header asks for. Trusting that header is the classic JWT bypass: an attacker
    re-signs with `alg: none` (or a weaker algorithm) and the signature check
    becomes a formality.
    """
    return jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
    )
