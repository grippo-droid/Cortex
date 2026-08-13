"""Per-user vector storage on ChromaDB.

Isolation model: one collection per user, named from the caller's `user_id` as
resolved from their JWT. This is the "silo" multi-tenancy pattern from the
architecture doc, chosen over a single pooled collection with metadata filters
because a forgotten filter in the pooled model leaks every tenant's data, while
the worst a bug can do here is address a collection that does not exist.

Two rules hold everywhere in this module:

1. A collection name is *derived*, never accepted. No caller passes one in;
   every public function takes `user_id` and builds the name itself.
2. Every read and write goes through `_collection_for_user`, so there is one
   place to audit.
"""

from functools import lru_cache
from typing import Any

import chromadb
from chromadb.api.models.Collection import Collection
from chromadb.config import Settings as ChromaSettings

from app.config import settings

_COLLECTION_PREFIX = "cortex_user_"


def collection_name_for_user(user_id: int) -> str:
    """Build a user's collection name. The id comes from the verified token."""
    if not isinstance(user_id, int) or isinstance(user_id, bool):
        # Defensive: a string here would let a caller name any collection.
        raise TypeError("user_id must be an int.")

    return f"{_COLLECTION_PREFIX}{user_id}"


@lru_cache(maxsize=1)
def _get_client() -> chromadb.ClientAPI:
    # Built lazily so importing the app does not create the storage directory.
    return chromadb.PersistentClient(
        path=settings.chroma_persist_dir,
        settings=ChromaSettings(anonymized_telemetry=False),
    )


def _collection_for_user(user_id: int) -> Collection:
    return _get_client().get_or_create_collection(
        name=collection_name_for_user(user_id),
        metadata={"hnsw:space": "cosine"},
    )


def _chunk_id(user_id: int, document_id: int, index: int) -> str:
    # Including user_id keeps ids unique even if collections are ever merged,
    # and makes a stray id obvious when debugging.
    return f"u{user_id}_d{document_id}_c{index}"


def add_document_chunks(
    user_id: int,
    document_id: int,
    filename: str,
    chunks: list[str],
    embeddings: list[list[float]],
) -> None:
    """Write a document's chunks into its owner's collection."""
    if not chunks:
        return

    if len(chunks) != len(embeddings):
        raise ValueError("Each chunk needs exactly one embedding.")

    collection = _collection_for_user(user_id)

    collection.add(
        ids=[_chunk_id(user_id, document_id, index) for index in range(len(chunks))],
        embeddings=embeddings,
        documents=chunks,
        metadatas=[
            {
                "document_id": document_id,
                "chunk_index": index,
                "filename": filename,
            }
            for index in range(len(chunks))
        ],
    )


def query_user_chunks(
    user_id: int, query_embedding: list[float], limit: int = 5
) -> list[dict[str, Any]]:
    """Similarity search, restricted to the caller's own collection."""
    collection = _collection_for_user(user_id)

    if collection.count() == 0:
        return []

    result = collection.query(
        query_embeddings=[query_embedding],
        n_results=min(limit, collection.count()),
    )

    documents = (result.get("documents") or [[]])[0]
    metadatas = (result.get("metadatas") or [[]])[0]
    distances = (result.get("distances") or [[]])[0]

    return [
        {
            "content": content,
            "metadata": metadata or {},
            "distance": distance,
        }
        for content, metadata, distance in zip(documents, metadatas, distances)
    ]


def delete_document_chunks(user_id: int, document_id: int) -> None:
    """Remove one document's chunks from its owner's collection."""
    _collection_for_user(user_id).delete(where={"document_id": document_id})


def delete_user_collection(user_id: int) -> None:
    """Drop a user's collection entirely."""
    try:
        _get_client().delete_collection(name=collection_name_for_user(user_id))
    except Exception:
        # Nothing stored for this user yet; deleting is still a success.
        pass


def reset_client_cache() -> None:
    """Drop the cached client so a new persist directory takes effect."""
    _get_client.cache_clear()
