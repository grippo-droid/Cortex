"""T3.5 — answer generation and streaming over the socket."""

import json

import pytest

from app.config import settings
from app.services import llm
from app.services.llm import ChatError
from tests.conftest import (
    DEFAULT_FAKE_TOKENS,
    FakeChatProvider,
    RecoveringChatProvider,
    register,
)

DOCUMENT = "The alpha project launch code is HELIOTROPE-9. " * 10
QUESTION = "What is the launch code?"


def prepare(client, email="alice@example.com"):
    """Register a user with one document and an open session."""
    user = register(client, email)
    client.post("/documents", headers=user["headers"], data={"text": DOCUMENT})
    session_id = client.post("/chat/sessions", headers=user["headers"], json={}).json()["id"]
    return user, session_id


def ask(client, user, session_id, question=QUESTION):
    """Ask one question and collect frames until the exchange ends.

    The server sends `done` whenever anything was generated, including a partial
    answer after a mid-stream failure. Only a failure before the first token
    ends with a bare `error`, so that is the one case to stop on.
    """
    frames = []
    saw_token = False

    with client.websocket_connect(f"/chat/stream/{session_id}") as socket:
        socket.send_text(json.dumps({"type": "auth", "token": user["token"]}))
        socket.receive_json()  # ready

        socket.send_text(json.dumps({"type": "message", "content": question}))

        while True:
            frame = socket.receive_json()
            frames.append(frame)
            kind = frame["type"]

            if kind == "token":
                saw_token = True
            if kind in {"done", "answer"}:
                break
            if kind == "error" and not saw_token:
                break

    return frames


def frames_of(frames, kind):
    return [f for f in frames if f["type"] == kind]


# --------------------------------------------------------------------------
# Streaming
# --------------------------------------------------------------------------


def test_answer_streams_token_by_token(client):
    user, session_id = prepare(client)

    frames = ask(client, user, session_id)

    tokens = [f["content"] for f in frames_of(frames, "token")]
    assert tokens == DEFAULT_FAKE_TOKENS


def test_frame_order_is_sources_start_tokens_done(client):
    user, session_id = prepare(client)

    order = [f["type"] for f in ask(client, user, session_id)]

    assert order[0] == "sources"
    assert order[1] == "start"
    assert order[-1] == "done"
    assert set(order[2:-1]) == {"token"}


def test_done_carries_the_whole_answer(client):
    user, session_id = prepare(client)

    frames = ask(client, user, session_id)
    done = frames_of(frames, "done")[0]

    assert done["content"] == "".join(DEFAULT_FAKE_TOKENS)
    assert done["partial"] is False


def test_the_prompt_reaching_the_provider_contains_the_context(client, fake_chat):
    user, session_id = prepare(client)

    ask(client, user, session_id)

    messages = fake_chat.calls[0]
    assert messages[0]["role"] == "system"
    assert "HELIOTROPE-9" in messages[-1]["content"]
    assert QUESTION in messages[-1]["content"]


def test_a_second_question_reuses_the_same_socket(client):
    user, session_id = prepare(client)

    with client.websocket_connect(f"/chat/stream/{session_id}") as socket:
        socket.send_text(json.dumps({"type": "auth", "token": user["token"]}))
        socket.receive_json()

        answers = []
        for _ in range(2):
            socket.send_text(json.dumps({"type": "message", "content": QUESTION}))
            while True:
                frame = socket.receive_json()
                if frame["type"] == "done":
                    answers.append(frame["content"])
                    break

    assert answers == ["".join(DEFAULT_FAKE_TOKENS)] * 2


# --------------------------------------------------------------------------
# Failure handling
# --------------------------------------------------------------------------


def test_failure_before_the_first_token_reports_an_error(client):
    user, session_id = prepare(client)
    llm.set_chat_provider(FakeChatProvider(fail_at=0, message="provider is down"))

    frames = ask(client, user, session_id)

    assert frames_of(frames, "token") == []
    assert "provider is down" in frames_of(frames, "error")[0]["detail"]
    # Nothing was generated, so nothing is claimed to have been.
    assert frames_of(frames, "done") == []


def test_failure_mid_stream_keeps_what_arrived(client):
    """The user should not watch a half-written answer disappear."""
    user, session_id = prepare(client)
    llm.set_chat_provider(FakeChatProvider(fail_at=3, message="connection reset"))

    frames = ask(client, user, session_id)

    tokens = [f["content"] for f in frames_of(frames, "token")]
    done = frames_of(frames, "done")[0]

    assert tokens == DEFAULT_FAKE_TOKENS[:3]
    assert done["content"] == "".join(DEFAULT_FAKE_TOKENS[:3])
    assert done["partial"] is True
    assert frames_of(frames, "error")


def test_a_transient_failure_before_any_token_is_retried(client):
    user, session_id = prepare(client)
    provider = RecoveringChatProvider()
    llm.set_chat_provider(provider)

    frames = ask(client, user, session_id)

    assert provider.attempts == 2
    assert frames_of(frames, "done")[0]["content"] == "".join(DEFAULT_FAKE_TOKENS)


def test_a_transient_failure_after_a_token_is_not_retried(client, monkeypatch):
    """Retrying mid-answer would repeat text the user has already read."""
    monkeypatch.setattr(settings, "llm_retry_base_seconds", 0.01)
    user, session_id = prepare(client)
    provider = FakeChatProvider(fail_at=2, transient=True)
    llm.set_chat_provider(provider)

    frames = ask(client, user, session_id)

    assert len(provider.calls) == 1
    assert [f["content"] for f in frames_of(frames, "token")] == DEFAULT_FAKE_TOKENS[:2]


def test_a_permanent_failure_is_not_retried(client):
    user, session_id = prepare(client)
    provider = FakeChatProvider(fail_at=0, transient=False)
    llm.set_chat_provider(provider)

    ask(client, user, session_id)

    assert len(provider.calls) == 1


def test_streaming_stops_at_the_timeout(client, monkeypatch):
    monkeypatch.setattr(settings, "llm_stream_timeout_seconds", 0.2)

    class Hanging:
        def stream(self, messages):
            import time

            yield "start"
            time.sleep(5)
            yield "never arrives"

    user, session_id = prepare(client)
    llm.set_chat_provider(Hanging())

    frames = ask(client, user, session_id)

    assert "too long" in frames_of(frames, "error")[0]["detail"]
    assert frames_of(frames, "done")[0]["partial"] is True


# --------------------------------------------------------------------------
# Provider selection
# --------------------------------------------------------------------------


def test_groq_provider_is_selected_by_name(monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", "gsk_test")

    provider = llm.build_provider("groq")

    assert isinstance(provider, llm.GroqChatProvider)
    assert provider._base_url == llm.GROQ_BASE_URL


def test_openai_provider_is_selected_by_name(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")

    provider = llm.build_provider("openai")

    assert isinstance(provider, llm.OpenAIChatProvider)
    assert provider._base_url is None


def test_groq_without_a_key_is_rejected(monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", None)

    with pytest.raises(ChatError, match="GROQ_API_KEY"):
        llm.build_provider("groq")


def test_unknown_provider_is_rejected():
    with pytest.raises(ChatError, match="Unknown"):
        llm.build_provider("ollama")


@pytest.mark.parametrize(
    ("status", "transient", "fragment"),
    [
        (401, False, "rejected the API key"),
        (429, True, "rate limiting"),
        (503, True, "temporarily unavailable"),
    ],
)
def test_provider_errors_are_translated(status, transient, fragment):
    error = llm._translate(type("E", (Exception,), {"status_code": status})())

    assert error.transient is transient
    assert fragment in str(error)
