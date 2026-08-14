"""Embedding provider selection, the local MiniLM backend, and retry policy."""

import pytest

from app.config import settings
from app.services.embeddings import (
    EmbeddingError,
    LocalMiniLMEmbeddingProvider,
    OpenAIEmbeddingProvider,
    _translate,
    build_provider,
    embed_texts,
    set_embedding_provider,
)


def test_local_provider_is_selected_by_name():
    assert isinstance(build_provider("local"), LocalMiniLMEmbeddingProvider)


def test_openai_provider_is_selected_by_name(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "sk-test-key")

    assert isinstance(build_provider("openai"), OpenAIEmbeddingProvider)


def test_openai_without_a_key_fails_with_a_useful_message(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", None)

    with pytest.raises(EmbeddingError, match="EMBEDDING_PROVIDER=local"):
        build_provider("openai")


def test_unknown_provider_is_rejected():
    with pytest.raises(EmbeddingError, match="Unknown"):
        build_provider("groq")


def test_empty_input_needs_no_model_load():
    """Must not pay the ONNX session cost just to embed nothing."""
    assert LocalMiniLMEmbeddingProvider().embed([]) == []


@pytest.mark.slow
def test_local_provider_produces_usable_vectors():
    """Exercises the real ONNX model; downloads ~80MB on a cold cache."""
    provider = LocalMiniLMEmbeddingProvider()

    vectors = provider.embed(
        ["The launch code is HELIOTROPE-9.", "Unrelated notes about gardening."]
    )

    assert len(vectors) == 2
    assert len(vectors[0]) == LocalMiniLMEmbeddingProvider.DIMENSIONS
    assert all(isinstance(value, float) for value in vectors[0])

    def cosine(a, b):
        dot = sum(x * y for x, y in zip(a, b))
        return dot / ((sum(x * x for x in a) ** 0.5) * (sum(y * y for y in b) ** 0.5))

    # Identical text embeds identically; unrelated text does not.
    assert cosine(vectors[0], vectors[0]) == pytest.approx(1.0, abs=1e-6)
    assert cosine(vectors[0], vectors[1]) < 0.8


@pytest.mark.slow
def test_local_and_openai_dimensions_differ():
    """The reason a provider switch requires re-uploading every document."""
    local_dimensions = len(LocalMiniLMEmbeddingProvider().embed(["probe"])[0])

    assert local_dimensions == 384
    # text-embedding-3-small is 1536; the mismatch is what Chroma rejects.
    assert local_dimensions != 1536


# --- reliability bounds (T4.5.2) ------------------------------------------


class _FlakyProvider:
    """Fails a set number of times, then returns a vector."""

    def __init__(self, failures: int, *, transient: bool = True) -> None:
        self.failures = failures
        self.transient = transient
        self.attempts = 0

    def embed(self, texts):
        self.attempts += 1
        if self.attempts <= self.failures:
            raise EmbeddingError("upstream wobble", transient=self.transient)
        return [[0.1] * 3 for _ in texts]


@pytest.fixture(autouse=True)
def _no_backoff_sleep(monkeypatch):
    """Keep the retry tests instant; the delay itself is not what is asserted."""
    monkeypatch.setattr("app.services.embeddings.time.sleep", lambda _seconds: None)


def test_transient_failure_is_retried_until_it_succeeds():
    provider = _FlakyProvider(failures=2)
    set_embedding_provider(provider)

    assert embed_texts(["chunk"]) == [[0.1, 0.1, 0.1]]
    assert provider.attempts == 3


def test_permanent_failure_is_not_retried():
    """A rejected key fails identically every time; retrying only adds delay."""
    provider = _FlakyProvider(failures=1, transient=False)
    set_embedding_provider(provider)

    with pytest.raises(EmbeddingError):
        embed_texts(["chunk"])

    assert provider.attempts == 1


def test_retries_are_capped(monkeypatch):
    monkeypatch.setattr(settings, "embedding_max_attempts", 3)
    provider = _FlakyProvider(failures=99)
    set_embedding_provider(provider)

    with pytest.raises(EmbeddingError):
        embed_texts(["chunk"])

    assert provider.attempts == 3


@pytest.mark.parametrize(
    ("status", "transient"),
    [(401, False), (429, True), (500, True), (503, True), (400, False)],
)
def test_status_codes_are_classified_for_retry(status, transient):
    error = _translate(type("Err", (Exception,), {"status_code": status})())

    assert error.transient is transient


def test_failures_without_a_status_are_treated_as_transient():
    """Connection resets and read timeouts arrive with no status code."""
    assert _translate(ConnectionError("connection reset")).transient is True


def test_openai_client_is_bounded(monkeypatch):
    """The SDK defaults to a 600s read timeout and two silent retries.

    Both are overridden, so an upload cannot hang for minutes and retries stay
    in `embed_texts` where the backoff is visible.
    """
    captured = {}

    class _FakeOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setitem(
        __import__("sys").modules, "openai", type("m", (), {"OpenAI": _FakeOpenAI})
    )

    OpenAIEmbeddingProvider(api_key="sk-test", model="m")._get_client()

    assert captured["timeout"] == settings.embedding_timeout_seconds
    assert captured["max_retries"] == 0
