"""Document ingestion: validate, extract, chunk, embed, persist.

Every function here takes `user_id` from the caller, which the route obtains
from `get_current_user`. Nothing in this module reads an owner from request
input.
"""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Document, DocumentStatus
from app.services import vector_store
from app.services.chunking import chunk_text
from app.services.embeddings import EmbeddingError, embed_texts
from app.services.text_extraction import ExtractionError

logger = logging.getLogger(__name__)

RAW_TEXT_FILENAME = "pasted-text.txt"


class DocumentNotFoundError(Exception):
    """No such document for this user. Also raised when it belongs to someone else."""


def list_documents(db: Session, user_id: int) -> list[Document]:
    return list(
        db.scalars(
            select(Document)
            .where(Document.user_id == user_id)
            .order_by(Document.uploaded_at.desc(), Document.id.desc())
        )
    )


def count_documents(db: Session, user_id: int) -> int:
    """How many documents this user has, used to word an empty search result."""
    return len(
        db.scalars(select(Document.id).where(Document.user_id == user_id)).all()
    )


def get_document(db: Session, user_id: int, document_id: int) -> Document:
    """Fetch one document, scoped to its owner.

    The user_id predicate is what makes an id from the URL safe to use. A
    missing row and someone else's row are deliberately indistinguishable, so
    the endpoint cannot be used to probe which ids exist.
    """
    document = db.scalar(
        select(Document).where(
            Document.id == document_id, Document.user_id == user_id
        )
    )

    if document is None:
        raise DocumentNotFoundError(str(document_id))

    return document


def create_pending_document(db: Session, user_id: int, filename: str) -> Document:
    """Record the upload before any of the slow work begins.

    Committed on its own so the row exists the moment the request returns, which
    is what lets the dashboard show the document as pending while it is being
    processed.
    """
    document = Document(
        user_id=user_id,
        filename=filename,
        status=DocumentStatus.PENDING,
        chunk_count=0,
    )
    db.add(document)
    db.commit()
    db.refresh(document)

    return document


def process_document(document_id: int, user_id: int, filename: str, text: str) -> None:
    """Chunk, embed, and store a document, off the request path.

    Opens its own session: this runs after the response has been sent, and the
    request-scoped session from `get_db` is closed by then.

    `user_id` is passed in from the route, where it came from the verified
    token. It is used both to scope the update and to choose the vector
    collection, so a background task can only ever write to the collection of
    the user who uploaded the document.
    """
    with SessionLocal() as db:
        document = db.scalar(
            select(Document).where(
                Document.id == document_id, Document.user_id == user_id
            )
        )
        if document is None:
            # Deleted between the upload returning and this task running.
            logger.info(
                "Skipping ingestion for document %s: no longer present", document_id
            )
            return

        document.status = DocumentStatus.PROCESSING
        db.commit()

        try:
            chunks = chunk_text(text)

            if not chunks:
                raise ExtractionError("The document contained no usable text.")

            embeddings = embed_texts(chunks)

            vector_store.add_document_chunks(
                user_id=user_id,
                document_id=document.id,
                filename=filename,
                chunks=chunks,
                embeddings=embeddings,
            )
        except Exception as exc:
            document.status = DocumentStatus.FAILED
            # The upload response has already been sent, so this message is the
            # only thing left explaining what went wrong.
            document.error = str(exc) or exc.__class__.__name__
            db.commit()
            logger.exception(
                "Ingestion failed for document %s (user %s)", document.id, user_id
            )
            return

        document.chunk_count = len(chunks)
        document.status = DocumentStatus.READY
        document.error = None
        db.commit()


def ingest_document(
    db: Session, user_id: int, filename: str, text: str
) -> Document:
    """Ingest synchronously, start to finish.

    Kept for callers that need the finished document rather than a pending one,
    and used by the tests to exercise the pipeline without a background task.
    """
    document = create_pending_document(db, user_id=user_id, filename=filename)
    process_document(
        document_id=document.id, user_id=user_id, filename=filename, text=text
    )
    db.refresh(document)

    return document


def delete_document(db: Session, user_id: int, document_id: int) -> None:
    """Delete a document and its vectors, scoped to its owner."""
    document = get_document(db, user_id, document_id)

    # Vectors first: a leftover row is recoverable, orphaned vectors that still
    # answer queries are not.
    vector_store.delete_document_chunks(user_id=user_id, document_id=document.id)

    db.delete(document)
    db.commit()


__all__ = [
    "DocumentNotFoundError",
    "EmbeddingError",
    "RAW_TEXT_FILENAME",
    "create_pending_document",
    "delete_document",
    "get_document",
    "ingest_document",
    "list_documents",
    "process_document",
]
