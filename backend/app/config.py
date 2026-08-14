"""Application configuration, loaded from environment variables / .env."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

# The value shipped in .env.example. Booting with it would mean signing tokens
# with a secret that is public in the repository.
PLACEHOLDER_JWT_SECRET = "change-me-to-a-long-random-string"
MIN_JWT_SECRET_LENGTH = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Auth
    jwt_secret: str = "change-me-to-a-long-random-string"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440

    # AI provider. Optional so Phase 0/1 run without a key; required from Phase 2.
    openai_api_key: str | None = None
    embedding_model: str = "text-embedding-3-small"
    chat_model: str = "gpt-4o-mini"

    # Which backend produces embeddings.
    #   openai - text-embedding-3-small, 1536 dimensions, needs credit
    #   local  - all-MiniLM-L6-v2 via the ONNX runtime chromadb already ships,
    #            384 dimensions, no key, no cost
    # Vectors are not interchangeable between the two: switching means
    # re-uploading every document. See the README.
    embedding_provider: Literal["openai", "local"] = "openai"

    # Which backend generates answers. Groq is OpenAI-compatible, so both use
    # the same client with a different base URL. Unlike embeddings, switching
    # here is free: nothing generated is stored, so no re-upload is needed.
    chat_provider: Literal["openai", "groq"] = "openai"
    groq_api_key: str | None = None
    groq_chat_model: str = "llama-3.3-70b-versatile"

    # Reliability bounds for the provider (architecture doc section 7.6).
    llm_timeout_seconds: float = 60.0
    llm_stream_timeout_seconds: float = 120.0
    llm_max_attempts: int = 3
    llm_retry_base_seconds: float = 0.5
    llm_temperature: float = 0.2

    # The same bounds for embeddings, which sit in the upload request path. The
    # OpenAI SDK defaults to a 600 second read timeout with two retries, so an
    # unbounded call can hold an upload open for many minutes before failing.
    embedding_timeout_seconds: float = 30.0
    embedding_max_attempts: int = 3
    embedding_retry_base_seconds: float = 0.5

    # Storage
    database_url: str = "sqlite:///./documind.db"
    chroma_persist_dir: str = "./chroma_data"

    # Uploads
    max_upload_mb: int = 10

    # Chunking. Sized in characters rather than tokens to avoid a tokeniser
    # dependency; roughly four characters per token, so 2000 is about 500
    # tokens, inside the 500-800 the architecture doc suggests.
    chunk_size: int = 2000
    chunk_overlap: int = 200

    # How many chunks to retrieve per question.
    retrieval_top_k: int = 5

    # Cosine distance (1 - cosine similarity) beyond which a retrieved chunk is
    # treated as unrelated to the question and dropped. Without it, an
    # out-of-scope question still returns the top k chunks however irrelevant,
    # and refusing depends on the model choosing to obey the system prompt
    # rather than on a code path.
    #
    # Measured on all-MiniLM-L6-v2 (docs/measurements/measure_distances.py):
    # questions the corpus answers peaked at 0.46, related-but-unanswered
    # questions ran 0.46-0.64, and unrelated questions started at 0.80. 0.75
    # sits in that gap, deliberately nearer the unrelated end: a false refusal
    # is worse than an occasional over-answer, and related-but-unanswered
    # questions are better refused by the model, which can explain itself.
    #
    # Scale is embedding-model-specific. Re-measure after changing provider.
    # Set to 0 or less to disable filtering.
    retrieval_max_distance: float = 0.75

    # Prompt budgets. Characters rather than tokens, for the same reason as
    # chunking: roughly four characters per token.
    max_history_messages: int = 10
    max_history_chars: int = 4000
    max_context_chars: int = 8000

    cors_origins: str = "http://localhost:3000"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()


def verify_jwt_secret(current: Settings | None = None) -> None:
    """Refuse to serve requests with a guessable signing key.

    A JWT is only as trustworthy as its secret: anyone who knows it can forge a
    token for any `sub`, and since every isolation check downstream trusts the
    `user_id` decoded from that token, a known secret is a full cross-tenant
    read of every user's documents and chats. Fail at startup instead.
    """
    current = current or settings

    if current.jwt_secret == PLACEHOLDER_JWT_SECRET:
        raise RuntimeError(
            "JWT_SECRET is still the placeholder value from .env.example. "
            "Generate a real one with:\n"
            '    python -c "import secrets; print(secrets.token_urlsafe(48))"'
        )

    if len(current.jwt_secret.strip()) < MIN_JWT_SECRET_LENGTH:
        raise RuntimeError(
            f"JWT_SECRET must be at least {MIN_JWT_SECRET_LENGTH} characters; "
            f"got {len(current.jwt_secret.strip())}."
        )
