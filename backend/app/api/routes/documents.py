"""Document routes. Ownership always comes from the token, never the request."""

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.config import settings
from app.database import get_db
from app.models import User
from app.schemas.document import DocumentRead
from app.services import document_service
from app.services.text_extraction import (
    ExtractionError,
    UnsupportedFileTypeError,
    ensure_supported,
    extract_text,
    sanitise_filename,
)

router = APIRouter(prefix="/documents", tags=["documents"])

_READ_CHUNK_BYTES = 64 * 1024


async def _read_within_limit(upload: UploadFile, max_bytes: int) -> bytes:
    """Read an upload, aborting as soon as it exceeds the limit.

    Reading the whole file and then checking its length would already have
    buffered it: a multi-gigabyte upload would exhaust memory before the check
    ran. This costs at most `max_bytes` plus one block.
    """
    parts: list[bytes] = []
    total = 0

    while True:
        block = await upload.read(_READ_CHUNK_BYTES)
        if not block:
            break

        total += len(block)
        if total > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File exceeds the {settings.max_upload_mb}MB limit.",
            )

        parts.append(block)

    return b"".join(parts)


@router.post("", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile | None = File(default=None),
    text: str | None = Form(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DocumentRead:
    """Accept a file or a block of raw text, and ingest it for the caller.

    Validation and text extraction happen here, so an unsupported file type or
    an oversized upload is still refused immediately with a useful status code.
    Only chunking, embedding, and the vector write are deferred: those are the
    slow parts, and their failures are recorded on the document instead.
    """
    has_file = file is not None and bool(file.filename)
    has_text = text is not None and bool(text.strip())

    if has_file == has_text:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide exactly one of 'file' or 'text'.",
        )

    try:
        if has_file:
            assert file is not None  # narrowed by has_file
            filename = sanitise_filename(file.filename or "")
            ensure_supported(filename)
            raw = await _read_within_limit(file, settings.max_upload_bytes)
            content = extract_text(filename, raw)
        else:
            assert text is not None  # narrowed by has_text
            if len(text.encode("utf-8")) > settings.max_upload_bytes:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"Text exceeds the {settings.max_upload_mb}MB limit.",
                )
            filename = document_service.RAW_TEXT_FILENAME
            content = text
    except UnsupportedFileTypeError as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(exc)
        ) from None
    except ExtractionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from None

    # The row is committed now and the slow work is deferred, so a large upload
    # does not hold its request open for the whole embedding round trip. The
    # caller gets a pending document back and watches it settle.
    document = document_service.create_pending_document(
        db, user_id=current_user.id, filename=filename
    )

    background_tasks.add_task(
        document_service.process_document,
        document_id=document.id,
        # From the verified token, never from request input: this is what scopes
        # the vector write to the uploader.
        user_id=current_user.id,
        filename=filename,
        text=content,
    )

    return DocumentRead.model_validate(document)


@router.get("", response_model=list[DocumentRead])
def list_documents(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[DocumentRead]:
    documents = document_service.list_documents(db, user_id=current_user.id)
    return [DocumentRead.model_validate(document) for document in documents]


@router.get("/{document_id}", response_model=DocumentRead)
def read_document(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DocumentRead:
    try:
        document = document_service.get_document(
            db, user_id=current_user.id, document_id=document_id
        )
    except document_service.DocumentNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Document not found."
        ) from None

    return DocumentRead.model_validate(document)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    try:
        document_service.delete_document(
            db, user_id=current_user.id, document_id=document_id
        )
    except document_service.DocumentNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Document not found."
        ) from None
