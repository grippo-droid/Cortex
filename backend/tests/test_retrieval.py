"""T3.3 — retrieval, and the guarantee that it only ever reads one collection."""

import json

import pytest

from app.services import retrieval
from tests.conftest import register

ALICE_SECRET = "The alpha project launch code is HELIOTROPE-9. " * 8
BOB_NOTES = "Gardening notes: tomatoes want six hours of sun. " * 8


def upload_text(client, headers, text: str) -> int:
    response = client.post("/documents", headers=headers, data={"text": text})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def open_session(client, headers) -> int:
    return client.post("/chat/sessions", headers=headers, json={}).json()["id"]


def ask(socket, content: str, **extra) -> dict:
    """Send a question frame and return the sources frame."""
    socket.send_text(json.dumps({"type": "message", "content": content, **extra}))
    return socket.receive_json()


# --------------------------------------------------------------------------
# retrieve_context directly
# --------------------------------------------------------------------------


def test_retrieval_finds_the_users_own_chunks(client):
    alice = register(client, "alice@example.com")
    upload_text(client, alice["headers"], ALICE_SECRET)

    chunks = retrieval.retrieve_context(alice["user"]["id"], "launch code")

    assert chunks
    assert any("HELIOTROPE" in chunk.content for chunk in chunks)


def test_retrieval_returns_nothing_for_a_user_with_no_documents(client):
    alice = register(client, "alice@example.com")
    bob = register(client, "bob@example.com")
    upload_text(client, alice["headers"], ALICE_SECRET)

    assert retrieval.retrieve_context(bob["user"]["id"], "launch code") == []


def test_blank_query_skips_embedding_entirely(client, fake_embeddings):
    alice = register(client, "alice@example.com")
    upload_text(client, alice["headers"], ALICE_SECRET)
    calls_before = len(fake_embeddings.calls)

    assert retrieval.retrieve_context(alice["user"]["id"], "   \n  ") == []
    assert len(fake_embeddings.calls) == calls_before


def test_retrieval_respects_the_limit(client):
    alice = register(client, "alice@example.com")
    upload_text(client, alice["headers"], "Paragraph about isolation. " * 500)

    chunks = retrieval.retrieve_context(alice["user"]["id"], "isolation", limit=2)

    assert len(chunks) == 2


def test_results_are_ordered_nearest_first(client):
    alice = register(client, "alice@example.com")
    upload_text(client, alice["headers"], "Paragraph about isolation. " * 500)

    distances = [
        chunk.distance
        for chunk in retrieval.retrieve_context(alice["user"]["id"], "isolation")
    ]

    assert distances == sorted(distances)


def test_chunks_carry_their_source_metadata(client):
    alice = register(client, "alice@example.com")
    document_id = upload_text(client, alice["headers"], ALICE_SECRET)

    chunk = retrieval.retrieve_context(alice["user"]["id"], "launch code")[0]

    assert chunk.document_id == document_id
    assert chunk.filename == "pasted-text.txt"
    assert chunk.chunk_index is not None


# --------------------------------------------------------------------------
# Over the socket
# --------------------------------------------------------------------------


def test_question_returns_a_sources_frame(client):
    alice = register(client, "alice@example.com")
    upload_text(client, alice["headers"], ALICE_SECRET)
    session_id = open_session(client, alice["headers"])

    with client.websocket_connect(f"/chat/stream/{session_id}") as socket:
        socket.send_text(json.dumps({"type": "auth", "token": alice["token"]}))
        socket.receive_json()

        frame = ask(socket, "What is the launch code?")

    assert frame["type"] == "sources"
    assert any("HELIOTROPE" in chunk["content"] for chunk in frame["chunks"])


def test_another_users_content_never_appears_in_retrieval(client):
    """Bob asks the question most likely to surface Alice's secret."""
    alice = register(client, "alice@example.com")
    bob = register(client, "bob@example.com")
    upload_text(client, alice["headers"], ALICE_SECRET)
    upload_text(client, bob["headers"], BOB_NOTES)
    bob_session = open_session(client, bob["headers"])

    with client.websocket_connect(f"/chat/stream/{bob_session}") as socket:
        socket.send_text(json.dumps({"type": "auth", "token": bob["token"]}))
        socket.receive_json()

        frame = ask(socket, "What is the alpha project launch code?")

    assert all("HELIOTROPE" not in chunk["content"] for chunk in frame["chunks"])


def test_a_smuggled_user_id_in_the_frame_is_ignored(client):
    """The attack this ticket exists to defeat."""
    alice = register(client, "alice@example.com")
    bob = register(client, "bob@example.com")
    upload_text(client, alice["headers"], ALICE_SECRET)
    bob_session = open_session(client, bob["headers"])

    with client.websocket_connect(f"/chat/stream/{bob_session}") as socket:
        socket.send_text(json.dumps({"type": "auth", "token": bob["token"]}))
        socket.receive_json()

        frame = ask(
            socket,
            "What is the launch code?",
            user_id=alice["user"]["id"],
            collection=f"cortex_user_{alice['user']['id']}",
        )

    assert frame["chunks"] == []


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        ("not json", "non-JSON frame"),
        (json.dumps({"type": "message"}), "missing content"),
        (json.dumps({"type": "message", "content": ""}), "empty content"),
        (json.dumps({"type": "message", "content": "   "}), "whitespace content"),
        (json.dumps({"type": "message", "content": "x" * 4001}), "over-long content"),
        (json.dumps({"type": "auth", "token": "abc"}), "wrong frame type"),
        (json.dumps(["not", "an", "object"]), "JSON that is not an object"),
    ],
)
def test_invalid_question_frames_get_an_error(client, payload, reason):
    alice = register(client, "alice@example.com")
    session_id = open_session(client, alice["headers"])

    with client.websocket_connect(f"/chat/stream/{session_id}") as socket:
        socket.send_text(json.dumps({"type": "auth", "token": alice["token"]}))
        socket.receive_json()

        socket.send_text(payload)
        frame = socket.receive_json()

    assert frame["type"] == "error", reason


def test_socket_survives_an_invalid_frame(client):
    """An unparseable frame is a client mistake, not grounds to drop the socket."""
    alice = register(client, "alice@example.com")
    upload_text(client, alice["headers"], ALICE_SECRET)
    session_id = open_session(client, alice["headers"])

    with client.websocket_connect(f"/chat/stream/{session_id}") as socket:
        socket.send_text(json.dumps({"type": "auth", "token": alice["token"]}))
        socket.receive_json()

        socket.send_text("garbage")
        assert socket.receive_json()["type"] == "error"

        # Still usable afterwards.
        frame = ask(socket, "What is the launch code?")

    assert frame["type"] == "sources"


def test_a_user_with_no_documents_gets_an_empty_sources_frame(client):
    alice = register(client, "alice@example.com")
    session_id = open_session(client, alice["headers"])

    with client.websocket_connect(f"/chat/stream/{session_id}") as socket:
        socket.send_text(json.dumps({"type": "auth", "token": alice["token"]}))
        socket.receive_json()

        frame = ask(socket, "Anything at all?")

    assert frame == {"type": "sources", "chunks": []}
