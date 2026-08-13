"""Retrieval: turn a question into context drawn only from one user's documents."""

from dataclasses import dataclass

from app.config import settings
from app.services import vector_store
from app.services.embeddings import embed_texts


@dataclass(frozen=True)
class RetrievedChunk:
    content: str
    document_id: int | None
    filename: str | None
    chunk_index: int | None
    distance: float | None


def retrieve_context(
    user_id: int, query: str, limit: int | None = None
) -> list[RetrievedChunk]:
    """Find the passages most similar to `query` among one user's documents.

    `user_id` must come from a verified token. It is the only thing deciding
    which collection is searched, and no other argument can widen that: the
    collection name is derived from it inside the vector store rather than being
    passed in from anywhere.
    """
    cleaned = query.strip()
    if not cleaned:
        # Nothing to search for, and no reason to spend an embedding call.
        return []

    top_k = settings.retrieval_top_k if limit is None else limit
    query_embedding = embed_texts([cleaned])[0]

    hits = vector_store.query_user_chunks(user_id, query_embedding, limit=top_k)

    return [
        RetrievedChunk(
            content=hit["content"],
            document_id=hit["metadata"].get("document_id"),
            filename=hit["metadata"].get("filename"),
            chunk_index=hit["metadata"].get("chunk_index"),
            distance=hit.get("distance"),
        )
        for hit in hits
    ]
