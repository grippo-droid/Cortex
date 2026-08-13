"""Document ingestion: validate, extract, chunk, embed, persist.

Every function here takes `user_id` from the caller, which the route obtains
from `get_current_user`. Nothing in this module reads an owner from request
input.
"""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

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


def ingest_document(
    db: Session, user_id: int, filename: str, text: str
) -> Document:
    """Chunk, embed, and store a document for one user."""
    document = Document(
        user_id=user_id,
        filename=filename,
        status=DocumentStatus.PROCESSING,
        chunk_count=0,
    )
    db.add(document)
    db.commit()
    db.refresh(document)

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
    except Exception:
        document.status = DocumentStatus.FAILED
        db.commit()
        logger.exception(
            "Ingestion failed for document %s (user %s)", document.id, user_id
        )
        raise

    document.chunk_count = len(chunks)
    document.status = DocumentStatus.READY
    db.commit()
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
    "delete_document",
    "get_document",
    "ingest_document",
    "list_documents",
]
