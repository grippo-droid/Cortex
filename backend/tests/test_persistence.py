"""T3.6 — persisting the exchange, and the history it makes possible."""

import json

from app.services import chat_service, llm, prompting
from tests.conftest import DEFAULT_FAKE_TOKENS, FakeChatProvider, register

DOCUMENT = "The alpha project launch code is HELIOTROPE-9. " * 10
QUESTION = "What is the launch code?"
FULL_ANSWER = "".join(DEFAULT_FAKE_TOKENS)


def prepare(client, email="alice@example.com", with_document=True):
    user = register(client, email)
    if with_document:
        client.post("/documents", headers=user["headers"], data={"text": DOCUMENT})
    session_id = client.post("/chat/sessions", headers=user["headers"], json={}).json()["id"]
    return user, session_id


def ask(client, user, session_id, question=QUESTION):
    frames = []
    saw_token = False

    with client.websocket_connect(f"/chat/stream/{session_id}") as socket:
        socket.send_text(json.dumps({"type": "auth", "token": user["token"]}))
        socket.receive_json()
        socket.send_text(json.dumps({"type": "message", "content": question}))

        while True:
            frame = socket.receive_json()
            frames.append(frame)
            if frame["type"] == "token":
                saw_token = True
            if frame["type"] in {"done", "answer"}:
                break
            if frame["type"] == "error" and not saw_token:
                break

    return frames


def history(client, user, session_id):
    return client.get(
        f"/chat/sessions/{session_id}/messages", headers=user["headers"]
    ).json()


# --------------------------------------------------------------------------
# The basic exchange
# --------------------------------------------------------------------------


def test_both_sides_of_the_exchange_are_stored(client):
    user, session_id = prepare(client)

    ask(client, user, session_id)
    stored = history(client, user, session_id)

    assert [m["role"] for m in stored] == ["user", "assistant"]
    assert stored[0]["content"] == QUESTION
    assert stored[1]["content"] == FULL_ANSWER


def test_messages_are_returned_in_order_across_several_turns(client):
    user, session_id = prepare(client)

    ask(client, user, session_id, "first question")
    ask(client, user, session_id, "second question")

    stored = history(client, user, session_id)

    assert [m["role"] for m in stored] == ["user", "assistant", "user", "assistant"]
    assert stored[0]["content"] == "first question"
    assert stored[2]["content"] == "second question"


def test_the_zero_context_reply_is_stored(client):
    """A question with no answer beneath it would be a hole in the transcript."""
    user, session_id = prepare(client, with_document=False)

    ask(client, user, session_id)
    stored = history(client, user, session_id)

    assert [m["role"] for m in stored] == ["user", "assistant"]
    assert stored[1]["content"] == prompting.NO_DOCUMENTS_REPLY


# --------------------------------------------------------------------------
# Failure handling
# --------------------------------------------------------------------------


def test_the_question_survives_a_failure_before_any_token(client):
    user, session_id = prepare(client)
    llm.set_chat_provider(FakeChatProvider(fail_at=0, message="provider is down"))

    ask(client, user, session_id)
    stored = history(client, user, session_id)

    # The question is kept; nothing is invented in place of the answer.
    assert [m["role"] for m in stored] == ["user"]
    assert stored[0]["content"] == QUESTION


def test_a_partial_answer_is_stored_and_marked(client):
    user, session_id = prepare(client)
    llm.set_chat_provider(FakeChatProvider(fail_at=3, message="connection reset"))

    ask(client, user, session_id)
    stored = history(client, user, session_id)

    assert len(stored) == 2
    assert stored[1]["content"].startswith("".join(DEFAULT_FAKE_TOKENS[:3]))
    assert chat_service.INCOMPLETE_ANSWER_SUFFIX in stored[1]["content"]


def test_a_retried_answer_is_stored_once(client):
    """A transient failure and retry must not leave two assistant turns."""
    from tests.conftest import RecoveringChatProvider

    user, session_id = prepare(client)
    llm.set_chat_provider(RecoveringChatProvider())

    ask(client, user, session_id)
    stored = history(client, user, session_id)

    assert [m["role"] for m in stored] == ["user", "assistant"]
    assert stored[1]["content"] == FULL_ANSWER


# --------------------------------------------------------------------------
# History feeding back into the prompt
# --------------------------------------------------------------------------


def test_a_follow_up_question_carries_the_earlier_turns(client, fake_chat):
    """The first time the history path is exercised end to end."""
    user, session_id = prepare(client)

    ask(client, user, session_id, "first question")
    ask(client, user, session_id, "second question")

    second_prompt = fake_chat.calls[1]
    roles = [m["role"] for m in second_prompt]

    # system, prior user turn, prior assistant turn, current question
    assert roles == ["system", "user", "assistant", "user"]
    assert second_prompt[1]["content"] == "first question"
    assert second_prompt[2]["content"] == FULL_ANSWER
    assert "second question" in second_prompt[-1]["content"]


def test_the_current_question_is_not_duplicated_into_history(client, fake_chat):
    user, session_id = prepare(client)

    ask(client, user, session_id, "only question")

    prompt = fake_chat.calls[0]
    assert [m["role"] for m in prompt] == ["system", "user"]
    assert prompt[-1]["content"].count("only question") == 1


def test_history_is_trimmed_to_the_configured_budget(client, fake_chat, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "max_history_messages", 2)
    user, session_id = prepare(client)

    for index in range(4):
        ask(client, user, session_id, f"question {index}")

    last_prompt = fake_chat.calls[-1]
    # system + 2 history + question
    assert len(last_prompt) == 4


# --------------------------------------------------------------------------
# Scoping
# --------------------------------------------------------------------------


def test_messages_land_in_the_session_they_belong_to(client):
    user, first_session = prepare(client)
    second_session = client.post(
        "/chat/sessions", headers=user["headers"], json={}
    ).json()["id"]

    ask(client, user, first_session, "question for the first session")
    ask(client, user, second_session, "question for the second session")

    first = history(client, user, first_session)
    second = history(client, user, second_session)

    assert first[0]["content"] == "question for the first session"
    assert second[0]["content"] == "question for the second session"
    assert len(first) == len(second) == 2


def test_another_user_cannot_read_a_stored_transcript(client):
    alice, alice_session = prepare(client)
    bob = register(client, "bob@example.com")

    ask(client, alice, alice_session)

    response = client.get(
        f"/chat/sessions/{alice_session}/messages", headers=bob["headers"]
    )

    assert response.status_code == 404
    assert "HELIOTROPE" not in response.text


def test_deleting_the_session_removes_the_transcript(client, db):
    from app.models import Message

    user, session_id = prepare(client)
    ask(client, user, session_id)

    client.delete(f"/chat/sessions/{session_id}", headers=user["headers"])

    assert db.query(Message).filter(Message.session_id == session_id).count() == 0
