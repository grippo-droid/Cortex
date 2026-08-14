"""Response schemas for the document endpoints."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    uploaded_at: datetime
    chunk_count: int
    status: str
    # Only set when status is "failed": ingestion happens after the upload
    # response, so this is where the reason ends up.
    error: str | None = None
