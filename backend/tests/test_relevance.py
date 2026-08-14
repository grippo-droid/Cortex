"""Relevance filtering (ticket T5.1).

The point of the threshold is that refusing an out-of-scope question is a code
path rather than a hope that the model obeys the system prompt. These tests use
controlled distances: the fake embedding provider is hash-derived, so real
distances between its vectors carry no meaning. The threshold's actual value is
justified empirically by docs/measurements/measure_distances.py.
"""

import json

import pytest

from app.config import settings
from app.services import retrieval, vector_store
from app.services.prompting import NO_DOCUMENTS_REPLY, NO_MATCH_REPLY
from tests.conftest import register


@pytest.fixture
def threshold(monkeypatch):
    """Turn the filter back on; conftest disables it for the other suites."""
    monkeypatch.setattr(settings, "retrieval_max_distance", 0.75)
    return 0.75


def fake_hits(*distances: float) -> list[dict]:
    return [
        {
            "content": f"chunk at {distance}",
            "metadata": {"document_id": 1, "filename": "d.txt", "chunk_index": i},
            "distance": distance,
        }
        for i, distance in enumerate(distances)
    ]


# --- the predicate ---------------------------------------------------------


@pytest.mark.parametrize(
    ("distance", "expected"),
    [
        (0.0, True),
        (0.2684, True),  # measured: owner asking about their own memo
        (0.4587, True),  # measured: worst relevant question
        (0.6355, True),  # measured: worst near-miss, deliberately kept
        (0.75, True),  # the boundary itself is inclusive
        (0.7501, False),
        (0.7978, False),  # measured: best off-topic question
        (0.9730, False),  # measured: unrelated user asking the memo question
    ],
)
def test_relevance_boundary(distance, expected):
    assert retrieval.is_relevant(distance, 0.75) is expected


def test_missing_distance_is_kept():
    """Dropping a hit whose distance is unknown would refuse for the wrong reason."""
    assert retrieval.is_relevant(None, 0.75) is True


@pytest.mark.parametrize("disabled", [0.0, -1.0])
def test_non_positive_threshold_disables_filtering(disabled):
    assert retrieval.is_relevant(5.0, disabled) is True


# --- retrieve_context ------------------------------------------------------


def test_distant_chunks_are_dropped(client, threshold, monkeypatch):
    account = register(client, "filter@example.com")
    monkeypatch.setattr(
        vector_store, "query_user_chunks", lambda *a, **k: fake_hits(0.2, 0.9)
    )

    chunks = retrieval.retrieve_context(account["user"]["id"], "question")

    assert [c.distance for c in chunks] == [0.2]


def test_filtering_is_per_chunk_not_all_or_nothing(client, threshold, monkeypatch):
    """A partly answerable question keeps its relevant passages."""
    account = register(client, "partial@example.com")
    monkeypatch.setattr(
        vector_store,
        "query_user_chunks",
        lambda *a, **k: fake_hits(0.1, 0.8, 0.3, 0.95),
    )

    chunks = retrieval.retrieve_context(account["user"]["id"], "question")

    assert [c.distance for c in chunks] == [0.1, 0.3]


def test_everything_distant_retrieves_nothing(client, threshold, monkeypatch):
    account = register(client, "nothing@example.com")
    monkeypatch.setattr(
        vector_store, "query_user_chunks", lambda *a, **k: fake_hits(0.8, 0.9, 1.2)
    )

    assert retrieval.retrieve_context(account["user"]["id"], "question") == []


def test_explicit_max_distance_overrides_the_setting(client, threshold, monkeypatch):
    account = register(client, "override@example.com")
    monkeypatch.setattr(
        vector_store, "query_user_chunks", lambda *a, **k: fake_hits(0.2, 0.9)
    )

    chunks = retrieval.retrieve_context(
        account["user"]["id"], "question", max_distance=1.5
    )

    assert [c.distance for c in chunks] == [0.2, 0.9]


# --- the refusal the threshold exists to produce ---------------------------


def ask(client, token, session_id, question):
    with client.websocket_connect(f"/chat/stream/{session_id}") as socket:
        socket.send_text(json.dumps({"type": "auth", "token": token}))
        assert json.loads(socket.receive_text())["type"] == "ready"
        socket.send_text(json.dumps({"type": "message", "content": question}))

        frames = []
        while True:
            frame = json.loads(socket.receive_text())
            frames.append(frame)
            if frame.get("done") or frame.get("type") == "done":
                return frames


def test_out_of_scope_question_is_refused_without_calling_the_model(
    client, threshold, monkeypatch, fake_chat
):
    """The behaviour T5.1 asks for: refusal by code, not by model compliance."""
    account = register(client, "refuse@example.com")
    client.post(
        "/documents",
        files={"file": ("notes.txt", b"Tomatoes need six hours of sun." * 20)},
        headers=account["headers"],
    )
    session = client.post("/chat/sessions", json={}, headers=account["headers"]).json()

    monkeypatch.setattr(
        vector_store, "query_user_chunks", lambda *a, **k: fake_hits(0.95)
    )

    frames = ask(client, account["token"], session["id"], "Who won the 1998 World Cup?")

    answers = [f for f in frames if f.get("type") == "answer"]
    assert answers and answers[0]["content"] == NO_MATCH_REPLY
    # The whole point: no tokens were spent being told what we already knew.
    assert fake_chat.calls == []


def test_a_user_with_no_documents_still_gets_the_onboarding_reply(
    client, threshold, monkeypatch, fake_chat
):
    """The two refusals stay distinct once filtering can also empty the results."""
    account = register(client, "empty@example.com")
    session = client.post("/chat/sessions", json={}, headers=account["headers"]).json()

    frames = ask(client, account["token"], session["id"], "Anything at all?")

    answers = [f for f in frames if f.get("type") == "answer"]
    assert answers and answers[0]["content"] == NO_DOCUMENTS_REPLY
    assert fake_chat.calls == []
