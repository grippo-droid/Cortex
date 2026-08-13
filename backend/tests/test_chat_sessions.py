"""T3.1 — chat session endpoints, all scoped to their owner."""

import pytest

from app.models import ChatSession, Message
from tests.conftest import register

SESSION_NOT_FOUND = "Chat session not found."


def create_session(client, headers, title=None):
    payload = {} if title is None else {"title": title}
    return client.post("/chat/sessions", headers=headers, json=payload)


def seed_message(db, session_id: int, role: str, content: str) -> None:
    db.add(Message(session_id=session_id, role=role, content=content))
    db.commit()


# --------------------------------------------------------------------------
# Creating
# --------------------------------------------------------------------------


def test_create_session_returns_it(client):
    alice = register(client, "alice@example.com")

    response = create_session(client, alice["headers"])

    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "New chat"
    assert isinstance(body["id"], int)
    assert "created_at" in body


def test_create_session_accepts_a_title(client):
    alice = register(client, "alice@example.com")

    response = create_session(client, alice["headers"], "Quarterly planning")

    assert response.status_code == 201
    assert response.json()["title"] == "Quarterly planning"


def test_session_title_is_stripped(client):
    alice = register(client, "alice@example.com")

    response = create_session(client, alice["headers"], "  Padded title  ")

    assert response.json()["title"] == "Padded title"


@pytest.mark.parametrize("title", ["", "   ", "\n\t "])
def test_blank_title_is_rejected(client, title):
    alice = register(client, "alice@example.com")

    assert create_session(client, alice["headers"], title).status_code == 422


def test_overlong_title_is_rejected(client):
    alice = register(client, "alice@example.com")

    assert create_session(client, alice["headers"], "x" * 256).status_code == 422


def test_session_is_owned_by_its_creator(client, db):
    alice = register(client, "alice@example.com")

    session_id = create_session(client, alice["headers"]).json()["id"]

    assert db.get(ChatSession, session_id).user_id == alice["user"]["id"]


# --------------------------------------------------------------------------
# Listing
# --------------------------------------------------------------------------


def test_list_returns_only_the_callers_sessions(client):
    alice = register(client, "alice@example.com")
    bob = register(client, "bob@example.com")

    create_session(client, alice["headers"], "Alice planning")
    create_session(client, bob["headers"], "Bob planning")

    alice_titles = [s["title"] for s in client.get("/chat/sessions", headers=alice["headers"]).json()]
    bob_titles = [s["title"] for s in client.get("/chat/sessions", headers=bob["headers"]).json()]

    assert alice_titles == ["Alice planning"]
    assert bob_titles == ["Bob planning"]


def test_list_is_most_recent_first(client):
    alice = register(client, "alice@example.com")

    for title in ("first", "second", "third"):
        create_session(client, alice["headers"], title)

    titles = [s["title"] for s in client.get("/chat/sessions", headers=alice["headers"]).json()]

    assert titles == ["third", "second", "first"]


def test_new_user_has_no_sessions(client):
    alice = register(client, "alice@example.com")

    assert client.get("/chat/sessions", headers=alice["headers"]).json() == []


# --------------------------------------------------------------------------
# Reading, and the ownership gate
# --------------------------------------------------------------------------


def test_owner_can_read_their_session(client):
    alice = register(client, "alice@example.com")
    session_id = create_session(client, alice["headers"], "Mine").json()["id"]

    response = client.get(f"/chat/sessions/{session_id}", headers=alice["headers"])

    assert response.status_code == 200
    assert response.json()["title"] == "Mine"


def test_reading_another_users_session_returns_404(client):
    alice = register(client, "alice@example.com")
    bob = register(client, "bob@example.com")
    alice_session = create_session(client, alice["headers"]).json()["id"]

    response = client.get(f"/chat/sessions/{alice_session}", headers=bob["headers"])

    assert response.status_code == 404
    assert response.json()["detail"] == SESSION_NOT_FOUND


def test_missing_and_forbidden_sessions_are_indistinguishable(client):
    """Otherwise the endpoint reveals which session ids exist."""
    alice = register(client, "alice@example.com")
    bob = register(client, "bob@example.com")
    alice_session = create_session(client, alice["headers"]).json()["id"]

    forbidden = client.get(f"/chat/sessions/{alice_session}", headers=bob["headers"])
    missing = client.get("/chat/sessions/999999", headers=bob["headers"])

    assert forbidden.status_code == missing.status_code == 404
    assert forbidden.json() == missing.json()


# --------------------------------------------------------------------------
# Messages
# --------------------------------------------------------------------------


def test_messages_start_empty(client):
    alice = register(client, "alice@example.com")
    session_id = create_session(client, alice["headers"]).json()["id"]

    response = client.get(f"/chat/sessions/{session_id}/messages", headers=alice["headers"])

    assert response.status_code == 200
    assert response.json() == []


def test_messages_are_returned_oldest_first(client, db):
    alice = register(client, "alice@example.com")
    session_id = create_session(client, alice["headers"]).json()["id"]

    seed_message(db, session_id, "user", "first question")
    seed_message(db, session_id, "assistant", "first answer")
    seed_message(db, session_id, "user", "second question")

    contents = [
        m["content"]
        for m in client.get(
            f"/chat/sessions/{session_id}/messages", headers=alice["headers"]
        ).json()
    ]

    assert contents == ["first question", "first answer", "second question"]


def test_reading_another_users_messages_returns_404(client, db):
    """The history endpoint must not leak another tenant's conversation."""
    alice = register(client, "alice@example.com")
    bob = register(client, "bob@example.com")
    alice_session = create_session(client, alice["headers"]).json()["id"]
    seed_message(db, alice_session, "user", "The launch code is HELIOTROPE-9")

    response = client.get(
        f"/chat/sessions/{alice_session}/messages", headers=bob["headers"]
    )

    assert response.status_code == 404
    assert "HELIOTROPE" not in response.text


# --------------------------------------------------------------------------
# Deleting
# --------------------------------------------------------------------------


def test_owner_can_delete_their_session(client):
    alice = register(client, "alice@example.com")
    session_id = create_session(client, alice["headers"]).json()["id"]

    assert client.delete(f"/chat/sessions/{session_id}", headers=alice["headers"]).status_code == 204
    assert client.get("/chat/sessions", headers=alice["headers"]).json() == []


def test_deleting_another_users_session_is_refused(client):
    alice = register(client, "alice@example.com")
    bob = register(client, "bob@example.com")
    alice_session = create_session(client, alice["headers"]).json()["id"]

    response = client.delete(f"/chat/sessions/{alice_session}", headers=bob["headers"])

    assert response.status_code == 404
    # Alice's session is untouched.
    assert client.get(f"/chat/sessions/{alice_session}", headers=alice["headers"]).status_code == 200


def test_deleting_a_session_cascades_to_its_messages(client, db):
    alice = register(client, "alice@example.com")
    session_id = create_session(client, alice["headers"]).json()["id"]
    seed_message(db, session_id, "user", "question")
    seed_message(db, session_id, "assistant", "answer")

    client.delete(f"/chat/sessions/{session_id}", headers=alice["headers"])

    assert db.query(Message).filter(Message.session_id == session_id).count() == 0


# --------------------------------------------------------------------------
# Authentication
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/chat/sessions"),
        ("get", "/chat/sessions"),
        ("get", "/chat/sessions/1"),
        ("get", "/chat/sessions/1/messages"),
        ("delete", "/chat/sessions/1"),
    ],
)
def test_every_endpoint_requires_authentication(client, method, path):
    assert getattr(client, method)(path).status_code == 401
