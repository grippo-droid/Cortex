"""T1.2 — the JWT_SECRET startup guard."""

import pytest

from app.config import (
    MIN_JWT_SECRET_LENGTH,
    PLACEHOLDER_JWT_SECRET,
    Settings,
    verify_jwt_secret,
)


def settings_with(secret: str) -> Settings:
    # _env_file=None keeps the developer's real .env out of the fixture.
    return Settings(jwt_secret=secret, _env_file=None)


def test_placeholder_secret_is_rejected():
    with pytest.raises(RuntimeError, match="placeholder"):
        verify_jwt_secret(settings_with(PLACEHOLDER_JWT_SECRET))


def test_short_secret_is_rejected():
    with pytest.raises(RuntimeError, match="at least"):
        verify_jwt_secret(settings_with("a" * (MIN_JWT_SECRET_LENGTH - 1)))


def test_blank_secret_is_rejected():
    with pytest.raises(RuntimeError):
        verify_jwt_secret(settings_with("   " * 20))


def test_real_secret_is_accepted():
    verify_jwt_secret(settings_with("x" * MIN_JWT_SECRET_LENGTH))
