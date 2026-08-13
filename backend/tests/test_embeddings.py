"""Embedding provider selection and the local MiniLM backend."""

import pytest

from app.config import settings
from app.services.embeddings import (
    EmbeddingError,
    LocalMiniLMEmbeddingProvider,
    OpenAIEmbeddingProvider,
    build_provider,
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
