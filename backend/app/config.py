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

    # Storage
    database_url: str = "sqlite:///./cortex.db"
    chroma_persist_dir: str = "./chroma_data"

    # Uploads
    max_upload_mb: int = 10

    # Chunking. Sized in characters rather than tokens to avoid a tokeniser
    # dependency; roughly four characters per token, so 2000 is about 500
    # tokens, inside the 500-800 the architecture doc suggests.
    chunk_size: int = 2000
    chunk_overlap: int = 200

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
