"""Structured request logging (ticket T4.5.3).

`configure_logging` replaces the root handlers at startup, which would discard
pytest's own `caplog` handler, so these tests capture on the `cortex.request`
logger directly instead.
"""

import json
import logging
import time

import pytest

from app.observability import (
    JsonFormatter,
    request_id_var,
    user_id_var,
)
from tests.conftest import register


class _CaptureHandler(logging.Handler):
    """Keep both the record and the JSON line it renders to."""

    def __init__(self) -> None:
        super().__init__()
        self.setFormatter(JsonFormatter())
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))

    @property
    def entries(self) -> list[dict]:
        return [json.loads(line) for line in self.lines]


def wait_for_websocket_entry(handler, timeout: float = 3.0) -> dict:
    """Wait for the socket's log line rather than assuming it has been written.

    The server side of a WebSocket finishes on the TestClient's own thread, so
    it can still be running when the `with` block exits. Asserting immediately
    passes or fails on timing.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        entry = next(
            (e for e in handler.entries if e.get("protocol") == "websocket"), None
        )
        if entry is not None:
            return entry
        time.sleep(0.01)

    raise AssertionError("no websocket log entry was written")


@pytest.fixture
def logs():
    handler = _CaptureHandler()
    logger = logging.getLogger("cortex.request")
    logger.addHandler(handler)
    previous_level = logger.level
    logger.setLevel(logging.INFO)

    yield handler

    logger.removeHandler(handler)
    logger.setLevel(previous_level)


def test_request_is_logged_as_one_json_object(client, logs):
    client.get("/documents")

    assert len(logs.entries) == 1
    entry = logs.entries[0]
    assert entry["message"] == "request completed"
    assert entry["method"] == "GET"
    assert entry["path"] == "/documents"
    assert entry["status"] == 401
    assert entry["level"] == "INFO"


def test_every_request_carries_an_id(client, logs):
    client.get("/documents")

    request_id = logs.entries[0]["request_id"]
    assert request_id
    assert isinstance(request_id, str)


def test_latency_is_recorded(client, logs):
    client.get("/documents")

    duration = logs.entries[0]["duration_ms"]
    assert isinstance(duration, (int, float))
    assert duration >= 0


def test_authenticated_request_records_the_user(client, logs):
    account = register(client, "logged@example.com")

    logs.lines.clear()
    client.get("/documents", headers=account["headers"])

    assert logs.entries[0]["user_id"] == account["user"]["id"]


def test_unauthenticated_request_records_no_user(client, logs):
    client.get("/documents")

    assert logs.entries[0]["user_id"] is None


def test_user_does_not_leak_between_requests(client, logs):
    """A stale context var would attribute one user's request to another."""
    account = register(client, "first@example.com")
    client.get("/documents", headers=account["headers"])

    logs.lines.clear()
    client.get("/documents")

    assert logs.entries[0]["user_id"] is None


def test_request_id_is_returned_to_the_caller(client):
    response = client.get("/documents")

    assert response.headers["x-request-id"]


def test_supplied_request_id_is_reused(client, logs):
    """Lets a trace started upstream continue through this service."""
    response = client.get("/documents", headers={"X-Request-ID": "trace-abc-123"})

    assert response.headers["x-request-id"] == "trace-abc-123"
    assert logs.entries[0]["request_id"] == "trace-abc-123"


def test_absurd_supplied_request_id_is_replaced(client, logs):
    """The value reaches the log verbatim, so it cannot be unbounded."""
    response = client.get("/documents", headers={"X-Request-ID": "x" * 500})

    assert response.headers["x-request-id"] != "x" * 500
    assert len(logs.entries[0]["request_id"]) <= 128


def test_health_checks_are_not_logged(client, logs):
    """Otherwise a liveness probe drowns out everything else."""
    client.get("/health")

    assert logs.entries == []


def test_websocket_connections_are_logged(client, logs):
    """The chat socket is the one route an HTTP-only middleware would miss."""
    with client.websocket_connect("/chat/stream/999999") as socket:
        socket.send_text(json.dumps({"type": "auth", "token": "not-a-token"}))
        with pytest.raises(Exception):
            socket.receive_text()

    entry = wait_for_websocket_entry(logs)
    assert entry["path"] == "/chat/stream/999999"
    assert entry["close_code"] == 1008


def test_authenticated_websocket_records_the_user(client, logs):
    """The success path sets the id on the socket scope, not the request scope."""
    account = register(client, "socket@example.com")
    session = client.post(
        "/chat/sessions", json={}, headers=account["headers"]
    ).json()

    logs.lines.clear()
    with client.websocket_connect(f"/chat/stream/{session['id']}") as socket:
        socket.send_text(json.dumps({"type": "auth", "token": account["token"]}))
        assert json.loads(socket.receive_text())["type"] == "ready"

    entry = wait_for_websocket_entry(logs)
    assert entry["user_id"] == account["user"]["id"]
    assert entry["accepted"] is True


def test_formatter_emits_extra_fields_and_omits_internals():
    record = logging.LogRecord(
        "cortex.request", logging.INFO, __file__, 1, "hello", (), None
    )
    record.user_id = 7
    record.duration_ms = 12.5

    payload = json.loads(JsonFormatter().format(record))

    assert payload["message"] == "hello"
    assert payload["user_id"] == 7
    assert payload["duration_ms"] == 12.5
    # Internals of the logging module must not end up in the log line.
    assert "args" not in payload
    assert "msg" not in payload


def test_formatter_includes_the_request_id_from_context():
    token = request_id_var.set("ctx-999")
    try:
        record = logging.LogRecord(
            "cortex.request", logging.INFO, __file__, 1, "hi", (), None
        )
        payload = json.loads(JsonFormatter().format(record))
    finally:
        request_id_var.reset(token)

    assert payload["request_id"] == "ctx-999"


def test_formatter_survives_unserialisable_values():
    """A stray object must not turn a log line into a crash."""
    record = logging.LogRecord(
        "cortex.request", logging.INFO, __file__, 1, "hi", (), None
    )
    record.thing = object()

    payload = json.loads(JsonFormatter().format(record))

    assert isinstance(payload["thing"], str)


def test_context_defaults_are_clean():
    assert request_id_var.get() is None
    assert user_id_var.get() is None
