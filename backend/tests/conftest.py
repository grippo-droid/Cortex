"""Shared test fixtures.

The DATABASE_URL and CHROMA_PERSIST_DIR overrides have to happen before anything
imports `app.config`, because Settings is instantiated at import time and
cached. Environment variables take precedence over the .env file, so this keeps
tests off the developer's real cortex.db and chroma_data.
"""

import hashlib
import os
import tempfile
from pathlib import Path

_TEST_ROOT = Path(tempfile.mkdtemp(prefix="cortex-tests-"))
os.environ["DATABASE_URL"] = f"sqlite:///{(_TEST_ROOT / 'test.db').as_posix()}"
os.environ["CHROMA_PERSIST_DIR"] = str(_TEST_ROOT / "chroma")
os.environ.setdefault("JWT_SECRET", "test-secret-not-used-in-production")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import models  # noqa: E402,F401  registers the tables on Base.metadata
from app.config import settings  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.services import vector_store  # noqa: E402
from app.services.embeddings import set_embedding_provider  # noqa: E402
from app.services.llm import ChatError, set_chat_provider  # noqa: E402

EMBEDDING_DIMENSIONS = 32


class FakeEmbeddingProvider:
    """Deterministic stand-in so the suite never calls a paid API.

    Hash-derived rather than random: identical text always embeds identically,
    and different text reliably differs, which is all the retrieval tests need.
    """

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [self._vector(text) for text in texts]

    @staticmethod
    def _vector(text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        raw = [digest[i % len(digest)] / 255.0 for i in range(EMBEDDING_DIMENSIONS)]
        magnitude = sum(value * value for value in raw) ** 0.5 or 1.0
        return [value / magnitude for value in raw]


DEFAULT_FAKE_TOKENS = ["The ", "launch ", "code ", "is ", "HELIOTROPE-9", "."]


class FakeChatProvider:
    """Scripted streaming provider, so the suite never spends real tokens.

    `fail_at` raises after that many fragments have been yielded; 0 fails before
    any output, which is the only point at which a retry is permitted.
    """

    def __init__(
        self,
        tokens: list[str] | None = None,
        fail_at: int | None = None,
        transient: bool = False,
        message: str = "provider exploded",
    ) -> None:
        self.tokens = DEFAULT_FAKE_TOKENS if tokens is None else tokens
        self.fail_at = fail_at
        self.transient = transient
        self.message = message
        self.calls: list[list[dict[str, str]]] = []

    def stream(self, messages):
        self.calls.append(messages)

        for index, token in enumerate(self.tokens):
            if self.fail_at is not None and index == self.fail_at:
                raise ChatError(self.message, transient=self.transient)
            yield token

        if self.fail_at is not None and self.fail_at >= len(self.tokens):
            raise ChatError(self.message, transient=self.transient)


class RecoveringChatProvider:
    """Fails transiently on the first attempt, then succeeds."""

    def __init__(self, tokens: list[str] | None = None) -> None:
        self.tokens = DEFAULT_FAKE_TOKENS if tokens is None else tokens
        self.attempts = 0

    def stream(self, messages):
        self.attempts += 1
        if self.attempts == 1:
            raise ChatError("temporary upstream failure", transient=True)
        yield from self.tokens


@pytest.fixture(autouse=True)
def fake_chat():
    """Every test gets the scripted provider unless it swaps in its own."""
    provider = FakeChatProvider()
    set_chat_provider(provider)
    yield provider
    set_chat_provider(None)


@pytest.fixture(autouse=True)
def _fresh_database():
    """Give every test an empty schema so tests cannot leak into each other."""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def fake_embeddings():
    """Swap in the fake provider for the duration of each test."""
    provider = FakeEmbeddingProvider()
    set_embedding_provider(provider)
    yield provider
    set_embedding_provider(None)


@pytest.fixture(autouse=True)
def _fresh_vector_store(tmp_path_factory):
    """Point each test at its own Chroma directory.

    Chroma persists to disk and keeps SQLite handles open, so on Windows a
    delete-between-tests approach fails silently and leaves the previous test's
    collections readable. That would let a genuine isolation failure pass
    unnoticed, so each test gets a directory of its own instead.
    """
    previous = settings.chroma_persist_dir
    settings.chroma_persist_dir = str(tmp_path_factory.mktemp("chroma"))
    vector_store.reset_client_cache()

    yield

    vector_store.reset_client_cache()
    settings.chroma_persist_dir = previous


@pytest.fixture
def client(_fresh_vector_store) -> TestClient:
    # Depends on the vector store fixture so the per-test directory is in place
    # before any request can touch Chroma.
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def register(client: TestClient, email: str, password: str = "correct-horse") -> dict:
    """Register a user and return {token, user, headers}."""
    response = client.post(
        "/auth/register", json={"email": email, "password": password}
    )
    assert response.status_code == 201, response.text
    body = response.json()

    return {
        "token": body["access_token"],
        "user": body["user"],
        "headers": {"Authorization": f"Bearer {body['access_token']}"},
    }
