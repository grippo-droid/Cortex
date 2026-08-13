"""Request and response schemas for the chat endpoints."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_TITLE_LENGTH = 255


class ChatSessionCreate(BaseModel):
    # Omit the field entirely to accept the default title; an explicitly blank
    # one is a mistake rather than a request for the default.
    title: str | None = Field(default=None, max_length=MAX_TITLE_LENGTH)

    @field_validator("title")
    @classmethod
    def _reject_blank_title(cls, value: str | None) -> str | None:
        if value is None:
            return None

        stripped = value.strip()
        if not stripped:
            raise ValueError("Title cannot be blank.")

        return stripped


class ChatSessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    created_at: datetime


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: str
    content: str
    created_at: datetime
