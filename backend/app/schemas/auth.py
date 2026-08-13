"""Request and response schemas for the auth endpoints."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

# bcrypt only hashes the first 72 bytes of a password and silently ignores the
# rest, so a longer password would be accepted while only partly verified.
MAX_PASSWORD_BYTES = 72


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)

    @field_validator("email")
    @classmethod
    def _normalise_email(cls, value: str) -> str:
        """Fold case so `A@x.com` and `a@x.com` cannot become two tenants."""
        return value.strip().lower()

    @field_validator("password")
    @classmethod
    def _reject_overlong_password(cls, value: str) -> str:
        # Measured in bytes, not characters: non-ASCII passwords hit the bcrypt
        # ceiling sooner than their length suggests.
        if len(value.encode("utf-8")) > MAX_PASSWORD_BYTES:
            raise ValueError(
                f"Password must be at most {MAX_PASSWORD_BYTES} bytes long."
            )
        return value


class UserRead(BaseModel):
    """Public view of a user. Deliberately omits `hashed_password`."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    created_at: datetime
