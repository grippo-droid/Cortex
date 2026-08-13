"""T1.3 — the get_current_user dependency, exercised through GET /auth/me."""

import base64
import json
from datetime import timedelta

import pytest
from jose import jwt

from app.api.deps import CREDENTIALS_ERROR_DETAIL
from app.config import settings
from app.core.security import create_access_token

ALICE = {"email": "alice@example.com", "password": "correct-horse"}
BOB = {"email": "bob@example.com", "password": "battery-staple"}


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def register(client, payload: dict) -> dict:
    """Register a user and return the AuthResponse body."""
    response = client.post("/auth/register", json=payload)
    assert response.status_code == 201
    return response.json()


def unsigned_token(claims: dict) -> str:
    """Hand-build an `alg: none` token; jose will not mint one for us."""

    def segment(data: dict) -> str:
        raw = json.dumps(data, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    return f"{segment({'alg': 'none', 'typ': 'JWT'})}.{segment(claims)}."


# --------------------------------------------------------------------------
# Accepting a legitimate caller
# --------------------------------------------------------------------------


def test_valid_token_resolves_the_caller(client):
    registered = register(client, ALICE)

    response = client.get("/auth/me", headers=auth(registered["access_token"]))

    assert response.status_code == 200
    assert response.json()["email"] == "alice@example.com"
    assert response.json()["id"] == registered["user"]["id"]


def test_token_resolves_to_its_own_owner_not_another_user(client):
    alice = register(client, ALICE)
    bob = register(client, BOB)
    assert alice["user"]["id"] != bob["user"]["id"]

    seen_by_alice = client.get("/auth/me", headers=auth(alice["access_token"])).json()
    seen_by_bob = client.get("/auth/me", headers=auth(bob["access_token"])).json()

    assert seen_by_alice["id"] == alice["user"]["id"]
    assert seen_by_bob["id"] == bob["user"]["id"]
    assert seen_by_alice["email"] == "alice@example.com"
    assert seen_by_bob["email"] == "bob@example.com"


def test_login_token_works_the_same_as_a_registration_token(client):
    register(client, ALICE)
    token = client.post("/auth/login", json=ALICE).json()["access_token"]

    response = client.get("/auth/me", headers=auth(token))

    assert response.status_code == 200
    assert response.json()["email"] == "alice@example.com"


# --------------------------------------------------------------------------
# Rejecting everything else
# --------------------------------------------------------------------------


def test_missing_authorization_header_is_rejected(client):
    response = client.get("/auth/me")

    assert response.status_code == 401
    assert response.json()["detail"] == CREDENTIALS_ERROR_DETAIL


@pytest.mark.parametrize(
    ("header", "reason"),
    [
        ({"Authorization": "Basic abc123"}, "wrong scheme"),
        ({"Authorization": "Bearer"}, "scheme with no token"),
        ({"Authorization": "abc123"}, "no scheme"),
        ({"Authorization": ""}, "empty header"),
    ],
)
def test_malformed_authorization_headers_are_rejected(client, header, reason):
    assert client.get("/auth/me", headers=header).status_code == 401, reason


def test_garbage_token_is_rejected(client):
    response = client.get("/auth/me", headers=auth("not-a-jwt"))

    assert response.status_code == 401


def test_token_signed_with_another_secret_is_rejected(client):
    """The forgery case: right shape, right claims, wrong signing key."""
    registered = register(client, ALICE)
    forged = jwt.encode(
        {"sub": str(registered["user"]["id"])},
        "an-attacker-chosen-secret-of-sufficient-length",
        algorithm=settings.jwt_algorithm,
    )

    response = client.get("/auth/me", headers=auth(forged))

    assert response.status_code == 401


def test_unsigned_alg_none_token_is_rejected(client):
    """A forged `alg: none` token must never bypass signature verification."""
    registered = register(client, ALICE)

    response = client.get(
        "/auth/me",
        headers=auth(unsigned_token({"sub": str(registered["user"]["id"])})),
    )

    assert response.status_code == 401


def test_token_signed_with_a_different_algorithm_is_rejected(client):
    registered = register(client, ALICE)
    other_algorithm = jwt.encode(
        {"sub": str(registered["user"]["id"])},
        settings.jwt_secret,
        algorithm="HS512",
    )

    response = client.get("/auth/me", headers=auth(other_algorithm))

    assert response.status_code == 401


def test_expired_token_is_rejected(client):
    registered = register(client, ALICE)
    expired = create_access_token(
        registered["user"]["id"], expires_delta=timedelta(seconds=-60)
    )

    response = client.get("/auth/me", headers=auth(expired))

    assert response.status_code == 401


def test_token_for_a_deleted_user_is_rejected(client, db):
    from app.models import User

    registered = register(client, ALICE)
    db.delete(db.get(User, registered["user"]["id"]))
    db.commit()

    response = client.get("/auth/me", headers=auth(registered["access_token"]))

    assert response.status_code == 401


@pytest.mark.parametrize(
    ("subject", "reason"),
    [
        ("not-a-number", "non-numeric subject"),
        (None, "missing subject"),
        ("999999", "subject with no matching row"),
    ],
)
def test_invalid_subject_claims_are_rejected(client, subject, reason):
    claims = {} if subject is None else {"sub": subject}
    token = jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)

    assert client.get("/auth/me", headers=auth(token)).status_code == 401, reason


def test_every_rejection_uses_the_same_message(client):
    """Divergent messages would let a caller tell forged from expired tokens."""
    registered = register(client, ALICE)
    expired = create_access_token(
        registered["user"]["id"], expires_delta=timedelta(seconds=-60)
    )

    bodies = [
        client.get("/auth/me").json(),
        client.get("/auth/me", headers=auth("not-a-jwt")).json(),
        client.get("/auth/me", headers=auth(expired)).json(),
    ]

    assert all(body == {"detail": CREDENTIALS_ERROR_DETAIL} for body in bodies)
