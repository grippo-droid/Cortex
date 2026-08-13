"""T3.2 — WebSocket authentication and session ownership.

Every refusal must be indistinguishable: a forged token, an expired one, a
session belonging to someone else, and a session that does not exist all have
to close the same way, or the socket becomes a probe for valid ids.
"""

import base64
import json
from datetime import timedelta

import pytest
from jose import jwt
from starlette.websockets import WebSocketDisconnect

from app.api import deps
from app.config import settings
from app.core.security import create_access_token
from tests.conftest import register

POLICY_VIOLATION = 1008


def auth_frame(token: str) -> str:
    return json.dumps({"type": "auth", "token": token})


def open_session(client, headers) -> int:
    response = client.post("/chat/sessions", headers=headers, json={})
    assert response.status_code == 201
    return response.json()["id"]


def connect_expecting_rejection(client, session_id, opening: str | None):
    """Open the socket, optionally send one frame, and capture the close code."""
    with pytest.raises(WebSocketDisconnect) as raised:
        with client.websocket_connect(f"/chat/stream/{session_id}") as socket:
            if opening is not None:
                socket.send_text(opening)
            socket.receive_json()

    return raised.value


def unsigned_token(claims: dict) -> str:
    def segment(data: dict) -> str:
        raw = json.dumps(data, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    return f"{segment({'alg': 'none', 'typ': 'JWT'})}.{segment(claims)}."


# --------------------------------------------------------------------------
# The happy path
# --------------------------------------------------------------------------


def test_owner_with_a_valid_token_is_accepted(client):
    alice = register(client, "alice@example.com")
    session_id = open_session(client, alice["headers"])

    with client.websocket_connect(f"/chat/stream/{session_id}") as socket:
        socket.send_text(auth_frame(alice["token"]))
        ready = socket.receive_json()

    assert ready == {"type": "ready", "session_id": session_id}


def test_connection_stays_open_after_the_handshake(client):
    alice = register(client, "alice@example.com")
    session_id = open_session(client, alice["headers"])

    with client.websocket_connect(f"/chat/stream/{session_id}") as socket:
        socket.send_text(auth_frame(alice["token"]))
        socket.receive_json()

        socket.send_text(json.dumps({"type": "message", "content": "hello"}))
        sources = socket.receive_json()
        reply = socket.receive_json()

    # Retrieval answers first (T3.3). Generation lands in T3.5; until then the
    # socket says so explicitly rather than dropping the question.
    assert sources["type"] == "sources"
    assert reply["type"] == "error"


# --------------------------------------------------------------------------
# Rejections
# --------------------------------------------------------------------------


def test_silence_is_closed_at_the_timeout(client, monkeypatch):
    """A socket that never authenticates must not be left hanging."""
    monkeypatch.setattr(deps, "AUTH_FRAME_TIMEOUT_SECONDS", 0.3)
    alice = register(client, "alice@example.com")
    session_id = open_session(client, alice["headers"])

    closed = connect_expecting_rejection(client, session_id, None)

    assert closed.code == POLICY_VIOLATION


@pytest.mark.parametrize(
    ("opening", "reason"),
    [
        ("not json at all", "non-JSON opening frame"),
        (json.dumps(["not", "an", "object"]), "JSON that is not an object"),
        (json.dumps({"type": "message", "content": "hi"}), "wrong frame type"),
        (json.dumps({"type": "auth"}), "missing token"),
        (json.dumps({"type": "auth", "token": ""}), "empty token"),
        (json.dumps({"type": "auth", "token": 12345}), "non-string token"),
        (json.dumps({"type": "auth", "token": "not-a-jwt"}), "garbage token"),
    ],
)
def test_malformed_opening_frames_are_rejected(client, opening, reason):
    alice = register(client, "alice@example.com")
    session_id = open_session(client, alice["headers"])

    assert connect_expecting_rejection(client, session_id, opening).code == (
        POLICY_VIOLATION
    ), reason


def test_token_signed_with_another_secret_is_rejected(client):
    alice = register(client, "alice@example.com")
    session_id = open_session(client, alice["headers"])
    forged = jwt.encode(
        {"sub": str(alice["user"]["id"])},
        "an-attacker-chosen-secret-of-sufficient-length",
        algorithm=settings.jwt_algorithm,
    )

    assert connect_expecting_rejection(client, session_id, auth_frame(forged)).code == (
        POLICY_VIOLATION
    )


def test_unsigned_alg_none_token_is_rejected(client):
    alice = register(client, "alice@example.com")
    session_id = open_session(client, alice["headers"])
    token = unsigned_token({"sub": str(alice["user"]["id"])})

    assert connect_expecting_rejection(client, session_id, auth_frame(token)).code == (
        POLICY_VIOLATION
    )


def test_expired_token_is_rejected(client):
    alice = register(client, "alice@example.com")
    session_id = open_session(client, alice["headers"])
    expired = create_access_token(
        alice["user"]["id"], expires_delta=timedelta(seconds=-60)
    )

    assert connect_expecting_rejection(client, session_id, auth_frame(expired)).code == (
        POLICY_VIOLATION
    )


def test_token_for_a_deleted_user_is_rejected(client, db):
    from app.models import User

    alice = register(client, "alice@example.com")
    session_id = open_session(client, alice["headers"])

    db.delete(db.get(User, alice["user"]["id"]))
    db.commit()

    assert connect_expecting_rejection(
        client, session_id, auth_frame(alice["token"])
    ).code == POLICY_VIOLATION


# --------------------------------------------------------------------------
# The isolation case
# --------------------------------------------------------------------------


def test_another_users_session_is_refused(client):
    """Bob holds a perfectly valid token. The session is not his."""
    alice = register(client, "alice@example.com")
    bob = register(client, "bob@example.com")
    alice_session = open_session(client, alice["headers"])

    closed = connect_expecting_rejection(
        client, alice_session, auth_frame(bob["token"])
    )

    assert closed.code == POLICY_VIOLATION


def test_foreign_and_missing_sessions_close_identically(client):
    """The pair that matters: neither code nor reason may differ."""
    alice = register(client, "alice@example.com")
    bob = register(client, "bob@example.com")
    alice_session = open_session(client, alice["headers"])

    foreign = connect_expecting_rejection(
        client, alice_session, auth_frame(bob["token"])
    )
    missing = connect_expecting_rejection(client, 999999, auth_frame(bob["token"]))

    assert foreign.code == missing.code
    assert foreign.reason == missing.reason


def test_a_users_own_session_is_unaffected_by_a_foreign_attempt(client):
    alice = register(client, "alice@example.com")
    bob = register(client, "bob@example.com")
    alice_session = open_session(client, alice["headers"])

    connect_expecting_rejection(client, alice_session, auth_frame(bob["token"]))

    with client.websocket_connect(f"/chat/stream/{alice_session}") as socket:
        socket.send_text(auth_frame(alice["token"]))
        assert socket.receive_json()["type"] == "ready"
