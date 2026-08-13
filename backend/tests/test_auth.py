"""T1.1 — POST /auth/register. T1.2 — POST /auth/login."""

import pytest
from jose import jwt
from sqlalchemy import select

from app.config import settings
from app.core.security import verify_password
from app.models import User

VALID_PAYLOAD = {"email": "alice@example.com", "password": "correct-horse"}
INVALID_CREDENTIALS = "Incorrect email or password."


def decode(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])


# --------------------------------------------------------------------------
# Registration
# --------------------------------------------------------------------------


def test_register_creates_user(client):
    response = client.post("/auth/register", json=VALID_PAYLOAD)

    assert response.status_code == 201
    body = response.json()
    assert body["user"]["email"] == "alice@example.com"
    assert isinstance(body["user"]["id"], int)
    assert "created_at" in body["user"]


def test_register_returns_a_usable_token(client):
    body = client.post("/auth/register", json=VALID_PAYLOAD).json()

    assert body["token_type"] == "bearer"
    assert decode(body["access_token"])["sub"] == str(body["user"]["id"])


def test_register_response_never_exposes_password(client):
    response = client.post("/auth/register", json=VALID_PAYLOAD)

    assert "hashed_password" not in response.json()["user"]
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
    assert response.json()["user"]["email"] == "bob@example.com"
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


# --------------------------------------------------------------------------
# Login
# --------------------------------------------------------------------------


def test_login_returns_token_and_user(client):
    client.post("/auth/register", json=VALID_PAYLOAD)

    response = client.post("/auth/login", json=VALID_PAYLOAD)

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["user"]["email"] == "alice@example.com"
    assert "hashed_password" not in body["user"]


def test_login_token_subject_is_the_user_id(client):
    registered = client.post("/auth/register", json=VALID_PAYLOAD).json()

    token = client.post("/auth/login", json=VALID_PAYLOAD).json()["access_token"]

    assert decode(token)["sub"] == str(registered["user"]["id"])


def test_login_token_expiry_matches_configuration(client):
    client.post("/auth/register", json=VALID_PAYLOAD)

    claims = decode(client.post("/auth/login", json=VALID_PAYLOAD).json()["access_token"])

    assert claims["exp"] - claims["iat"] == settings.jwt_expire_minutes * 60


def test_login_with_wrong_password_is_rejected(client):
    client.post("/auth/register", json=VALID_PAYLOAD)

    response = client.post(
        "/auth/login",
        json={"email": VALID_PAYLOAD["email"], "password": "not-the-password"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == INVALID_CREDENTIALS


def test_login_with_unknown_email_is_rejected(client):
    response = client.post(
        "/auth/login",
        json={"email": "nobody@example.com", "password": "correct-horse"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == INVALID_CREDENTIALS


def test_wrong_password_and_unknown_email_are_indistinguishable(client):
    """Any difference here lets an attacker enumerate registered addresses."""
    client.post("/auth/register", json=VALID_PAYLOAD)

    wrong_password = client.post(
        "/auth/login",
        json={"email": VALID_PAYLOAD["email"], "password": "not-the-password"},
    )
    unknown_email = client.post(
        "/auth/login",
        json={"email": "nobody@example.com", "password": "correct-horse"},
    )

    assert wrong_password.status_code == unknown_email.status_code
    assert wrong_password.json() == unknown_email.json()


def test_login_is_case_insensitive_on_email(client):
    client.post("/auth/register", json=VALID_PAYLOAD)

    response = client.post(
        "/auth/login",
        json={"email": "  ALICE@Example.COM  ", "password": VALID_PAYLOAD["password"]},
    )

    assert response.status_code == 200


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        ({"email": "alice@example.com"}, "missing password"),
        ({"password": "correct-horse"}, "missing email"),
        ({"email": "not-an-email", "password": "correct-horse"}, "malformed email"),
    ],
)
def test_login_invalid_payloads_are_rejected(client, payload, reason):
    assert client.post("/auth/login", json=payload).status_code == 422, reason


def test_login_with_overlong_password_does_not_error(client):
    """Must be a clean 4xx, never a 500 from bcrypt's 72-byte ceiling."""
    client.post("/auth/register", json=VALID_PAYLOAD)

    response = client.post(
        "/auth/login",
        json={"email": VALID_PAYLOAD["email"], "password": "a" * 200},
    )

    assert response.status_code == 422
