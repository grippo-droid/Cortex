"""Embedding providers, kept behind a small interface.

The architecture doc calls for the AI provider to be swappable. Everything
downstream depends on `EmbeddingProvider`, so changing provider means writing
one class and setting `EMBEDDING_PROVIDER`, not touching the pipeline.

Two are implemented:

* `openai`  - text-embedding-3-small, 1536 dimensions. The submission default.
* `local`   - all-MiniLM-L6-v2 through the ONNX runtime chromadb already
              depends on, 384 dimensions, no API key and no per-call cost.

Their vectors are not comparable. A collection embedded with one and queried
with the other is not merely less accurate, it is arithmetically invalid, and
Chroma rejects the dimension mismatch outright. Switching provider requires
re-uploading every document.

Groq is deliberately absent: it serves chat completions only and has no
embeddings endpoint, so it cannot back this interface.
"""

import random
import time
from typing import Protocol

from app.config import settings


class EmbeddingError(Exception):
    """The provider could not produce embeddings.

    `transient` marks failures worth retrying: rate limits, upstream 5xx, and
    connection problems. A rejected key or an over-long input fails identically
    on a second attempt, so those are raised immediately.
    """

    def __init__(self, message: str, *, transient: bool = False) -> None:
        super().__init__(message)
        self.transient = transient


class EmbeddingProvider(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input text, in the same order."""
        ...


def _translate(exc: Exception) -> EmbeddingError:
    """Turn a provider exception into something a user can act on."""
    status = getattr(exc, "status_code", None)

    if status == 401:
        return EmbeddingError(
            "The embedding provider rejected the API key. Check "
            "EMBEDDING_PROVIDER and the matching key in .env."
        )
    if status == 429:
        return EmbeddingError(
            "The embedding provider is rate limiting or out of quota. Try again "
            "shortly.",
            transient=True,
        )
    if status is not None and status >= 500:
        return EmbeddingError(
            "The embedding provider is temporarily unavailable.", transient=True
        )

    # Connection resets, DNS failures, and read timeouts arrive without a status.
    return EmbeddingError(
        str(exc) or "The embedding provider failed.", transient=status is None
    )


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

            self._client = OpenAI(
                api_key=self._api_key,
                # Without these the SDK defaults apply: a 600 second read
                # timeout and two silent retries, so a stalled connection can
                # hold an upload open for tens of minutes. Retries are handled
                # in `embed_texts` instead, where the backoff is visible.
                timeout=settings.embedding_timeout_seconds,
                max_retries=0,
            )

        return self._client

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        try:
            response = self._get_client().embeddings.create(
                model=self._model, input=texts
            )
        except Exception as exc:
            raise _translate(exc) from exc

        # The API documents input order preservation, but sorting by index makes
        # a mismatch impossible rather than merely unlikely: a shuffled vector
        # would silently attach the wrong embedding to a chunk.
        ordered = sorted(response.data, key=lambda item: item.index)
        return [item.embedding for item in ordered]


class LocalMiniLMEmbeddingProvider:
    """all-MiniLM-L6-v2, run locally through chromadb's bundled ONNX runtime.

    No API key and no per-call cost, which is why development runs on it. The
    model weights (about 80MB) download once to the user's cache directory on
    first use; every run after that is fully offline.
    """

    DIMENSIONS = 384

    def __init__(self) -> None:
        self._embedding_function = None

    def _get_embedding_function(self):
        # Loading the ONNX session is slow, so defer it until something is
        # actually embedded and keep it afterwards.
        if self._embedding_function is None:
            from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2

            self._embedding_function = ONNXMiniLM_L6_V2()

        return self._embedding_function

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        try:
            vectors = self._get_embedding_function()(texts)
        except Exception as exc:
            raise EmbeddingError(f"Local embedding model failed: {exc}") from exc

        # The ONNX function hands back numpy arrays; Chroma and the JSON layer
        # both want plain floats.
        return [[float(value) for value in vector] for vector in vectors]


_provider: EmbeddingProvider | None = None


def set_embedding_provider(provider: EmbeddingProvider | None) -> None:
    """Swap the provider. Used by the tests to avoid live API calls."""
    global _provider
    _provider = provider


def build_provider(name: str) -> EmbeddingProvider:
    """Construct the provider named by `EMBEDDING_PROVIDER`."""
    if name == "local":
        return LocalMiniLMEmbeddingProvider()

    if name == "openai":
        if not settings.openai_api_key:
            raise EmbeddingError(
                "EMBEDDING_PROVIDER is 'openai' but OPENAI_API_KEY is not set. "
                "Set the key, or use EMBEDDING_PROVIDER=local for a keyless "
                "local model."
            )
        return OpenAIEmbeddingProvider(
            api_key=settings.openai_api_key, model=settings.embedding_model
        )

    raise EmbeddingError(f"Unknown EMBEDDING_PROVIDER '{name}'.")


def get_embedding_provider() -> EmbeddingProvider:
    global _provider

    if _provider is None:
        _provider = build_provider(settings.embedding_provider)

    return _provider


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed `texts`, retrying transient provider failures with backoff.

    Unlike streaming a completion, an embedding call is atomic: it either
    returns every vector or none, so there is no partial output to duplicate and
    a retry is always safe.
    """
    provider = get_embedding_provider()
    delay = settings.embedding_retry_base_seconds

    for attempt in range(1, settings.embedding_max_attempts + 1):
        try:
            return provider.embed(texts)
        except EmbeddingError as error:
            last_attempt = attempt == settings.embedding_max_attempts
            if last_attempt or not error.transient:
                raise

        # Jitter so several uploads failing together do not retry in lockstep.
        time.sleep(delay + random.uniform(0, delay / 2))
        delay *= 2

    # Unreachable: the loop either returns or raises on the final attempt.
    raise EmbeddingError("Embedding failed.")
