"""Request and response schemas for the chat endpoints."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_TITLE_LENGTH = 255
MAX_QUESTION_LENGTH = 4000


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


class ChatQuestion(BaseModel):
    """An inbound question frame on the chat socket.

    Unknown fields are dropped rather than read. A frame carrying something like
    `user_id` must never influence which collection is searched: that comes from
    the token verified during the handshake and from nowhere else.
    """

    model_config = ConfigDict(extra="ignore")

    type: Literal["message"]
    content: str = Field(min_length=1, max_length=MAX_QUESTION_LENGTH)

    @field_validator("content")
    @classmethod
    def _require_substance(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Question cannot be blank.")
        return stripped
