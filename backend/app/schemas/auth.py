"""Request and response schemas for the auth endpoints."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

# bcrypt only hashes the first 72 bytes of a password and silently ignores the
# rest, so a longer password would be accepted while only partly verified.
MAX_PASSWORD_BYTES = 72


def _reject_overlong_password(value: str) -> str:
    # Measured in bytes, not characters: non-ASCII passwords hit the bcrypt
    # ceiling sooner than their length suggests.
    if len(value.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise ValueError(f"Password must be at most {MAX_PASSWORD_BYTES} bytes long.")
    return value


class _EmailPayload(BaseModel):
    email: EmailStr

    @field_validator("email")
    @classmethod
    def _normalise_email(cls, value: str) -> str:
        """Fold case so `A@x.com` and `a@x.com` cannot become two tenants."""
        return value.strip().lower()


class UserCreate(_EmailPayload):
    password: str = Field(min_length=8)

    _check_password = field_validator("password")(_reject_overlong_password)


class UserLogin(_EmailPayload):
    # No minimum here: the policy applies at registration, and rejecting a short
    # password on login would only confirm it could not belong to an account.
    password: str

    _check_password = field_validator("password")(_reject_overlong_password)


class UserRead(BaseModel):
    """Public view of a user. Deliberately omits `hashed_password`."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    created_at: datetime


class AuthResponse(BaseModel):
    """Returned by both register and login, so the client needs one round trip."""

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    user: UserRead
