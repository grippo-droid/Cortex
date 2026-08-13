"""Embedding provider, kept behind a small interface.

The architecture doc calls for the AI provider to be swappable. Everything
downstream depends on `EmbeddingProvider`, so moving to another provider means
writing one class, not touching the ingestion pipeline.
"""

from typing import Protocol

from app.config import settings


class EmbeddingError(Exception):
    """The provider could not produce embeddings."""


class EmbeddingProvider(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input text, in the same order."""
        ...


class OpenAIEmbeddingProvider:
    def __init__(self, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model
        self._client = None

    def _get_client(self):
        # Imported and constructed lazily so the app boots, and the tests run,
        # without an API key present.
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(api_key=self._api_key)

        return self._client

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        try:
            response = self._get_client().embeddings.create(
                model=self._model, input=texts
            )
        except Exception as exc:
            raise EmbeddingError(str(exc)) from exc

        # The API documents input order preservation, but sorting by index makes
        # a mismatch impossible rather than merely unlikely: a shuffled vector
        # would silently attach the wrong embedding to a chunk.
        ordered = sorted(response.data, key=lambda item: item.index)
        return [item.embedding for item in ordered]


_provider: EmbeddingProvider | None = None


def set_embedding_provider(provider: EmbeddingProvider | None) -> None:
    """Swap the provider. Used by the tests to avoid live API calls."""
    global _provider
    _provider = provider


def get_embedding_provider() -> EmbeddingProvider:
    global _provider

    if _provider is None:
        if not settings.openai_api_key:
            raise EmbeddingError(
                "OPENAI_API_KEY is not set, so documents cannot be embedded."
            )
        _provider = OpenAIEmbeddingProvider(
            api_key=settings.openai_api_key, model=settings.embedding_model
        )

    return _provider


def embed_texts(texts: list[str]) -> list[list[float]]:
    return get_embedding_provider().embed(texts)
