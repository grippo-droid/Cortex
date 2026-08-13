"""T1.1 — POST /auth/register."""

import pytest
from sqlalchemy import select

from app.core.security import verify_password
from app.models import User

VALID_PAYLOAD = {"email": "alice@example.com", "password": "correct-horse"}


def test_register_creates_user(client):
    response = client.post("/auth/register", json=VALID_PAYLOAD)

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "alice@example.com"
    assert isinstance(body["id"], int)
    assert "created_at" in body


def test_register_response_never_exposes_password(client):
    response = client.post("/auth/register", json=VALID_PAYLOAD)

    assert "hashed_password" not in response.json()
    assert VALID_PAYLOAD["password"] not in response.text


def test_password_is_stored_as_a_bcrypt_hash(client, db):
    client.post("/auth/register", json=VALID_PAYLOAD)

    user = db.scalar(select(User).where(User.email == "alice@example.com"))
    assert user is not None
    assert user.hashed_password != VALID_PAYLOAD["password"]
    assert user.hashed_password.startswith("$2b$")
    assert verify_password(VALID_PAYLOAD["password"], user.hashed_password)


def test_duplicate_email_is_rejected(client):
    assert client.post("/auth/register", json=VALID_PAYLOAD).status_code == 201

    response = client.post("/auth/register", json=VALID_PAYLOAD)

    assert response.status_code == 409
    assert response.json()["detail"] == "An account with this email already exists."


def test_duplicate_email_is_rejected_regardless_of_casing(client):
    client.post("/auth/register", json=VALID_PAYLOAD)

    response = client.post(
        "/auth/register",
        json={"email": "ALICE@Example.COM", "password": "another-password"},
    )

    assert response.status_code == 409


def test_email_is_stored_normalised(client, db):
    response = client.post(
        "/auth/register",
        json={"email": "  BOB@Example.COM  ", "password": "correct-horse"},
    )

    assert response.status_code == 201
    assert response.json()["email"] == "bob@example.com"
    assert db.scalar(select(User).where(User.email == "bob@example.com")) is not None


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        ({"email": "not-an-email", "password": "correct-horse"}, "malformed email"),
        ({"email": "carol@example.com", "password": "short"}, "password under 8 chars"),
        ({"email": "carol@example.com"}, "missing password"),
        ({"password": "correct-horse"}, "missing email"),
    ],
)
def test_invalid_payloads_are_rejected(client, payload, reason):
    assert client.post("/auth/register", json=payload).status_code == 422, reason


def test_password_at_bcrypt_limit_is_accepted(client):
    response = client.post(
        "/auth/register",
        json={"email": "erin@example.com", "password": "a" * 72},
    )

    assert response.status_code == 201


def test_password_longer_than_bcrypt_limit_is_rejected(client):
    """bcrypt ignores bytes past 72, so an over-long password must 422, not 500."""
    response = client.post(
        "/auth/register",
        json={"email": "dave@example.com", "password": "a" * 73},
    )

    assert response.status_code == 422


def test_password_length_is_measured_in_bytes_not_characters(client):
    """40 two-byte characters is 80 bytes: over the limit despite being 40 long."""
    response = client.post(
        "/auth/register",
        json={"email": "frank@example.com", "password": "é" * 40},
    )

    assert response.status_code == 422
