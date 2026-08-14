"""Structured request logging (ticket T4.5.3).

One JSON object per line, so logs can be shipped and queried without a parser
written against prose. Every record carries a request id, and requests that
reached authentication also carry the user id, which is what makes a report like
"user 4's uploads are timing out" answerable.

Two implementation notes worth keeping:

* This is a raw ASGI middleware rather than `BaseHTTPMiddleware`. That subclass
  runs the endpoint in a separate anyio task, so a `ContextVar` set inside a
  route or dependency is not visible when the middleware regains control, and
  every user id would log as null. A plain ASGI callable stays in the same
  context, so values set downstream are visible here.

* It handles `websocket` scopes as well as `http`, which is why the chat socket
  appears in the logs at all. WebSockets never produce an HTTP status, so the
  close code is recorded instead.
"""

import json
import logging
import sys
import time
import uuid
from contextvars import ContextVar

REQUEST_ID_HEADER = "x-request-id"

# Set per request by the middleware, and read by the log formatter.
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
# Set by `get_current_user` / `authenticate_websocket` once a token is verified.
user_id_var: ContextVar[int | None] = ContextVar("user_id", default=None)

# Health checks would otherwise dominate the log without saying anything.
QUIET_PATHS = {"/health"}

# Attributes present on every LogRecord; anything else was passed as `extra`
# and belongs in the JSON output.
_STANDARD_ATTRS = set(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__
) | {"message", "asctime", "taskName"}

logger = logging.getLogger("cortex.request")


class JsonFormatter(logging.Formatter):
    """Render a log record as a single JSON line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": time.strftime(
                "%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)
            )
            + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        request_id = request_id_var.get()
        if request_id is not None:
            payload["request_id"] = request_id

        # Anything handed to the call as `extra=`.
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS:
                payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


def configure_logging(level: int = logging.INFO) -> None:
    """Install the JSON formatter on the root logger.

    Uvicorn's own access log is silenced because the middleware below records
    the same requests with more detail; leaving both on would double every line.
    Startup and error logs from uvicorn are left alone.
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    logging.getLogger("uvicorn.access").handlers = []
    logging.getLogger("uvicorn.access").propagate = False


class RequestLoggingMiddleware:
    """Log one line per request with its id, user, outcome and latency."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        request_id = _incoming_request_id(scope) or uuid.uuid4().hex
        request_token = request_id_var.set(request_id)
        # Reset explicitly: under HTTP/2 or a reused context the previous
        # request's user must not leak into this one's logs.
        user_token = user_id_var.set(None)

        path = scope.get("path", "")
        started = time.perf_counter()
        outcome: dict[str, object] = {}

        async def send_wrapper(message) -> None:
            if message["type"] == "http.response.start":
                outcome["status"] = message["status"]
                # Echo the id so a client can quote it in a bug report.
                message.setdefault("headers", []).append(
                    (REQUEST_ID_HEADER.encode(), request_id.encode())
                )
            elif message["type"] == "websocket.accept":
                outcome["accepted"] = True
            elif message["type"] == "websocket.close":
                outcome["close_code"] = message.get("code", 1000)

            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            _emit(scope, path, outcome, started, failed=True)
            raise
        else:
            if path not in QUIET_PATHS:
                _emit(scope, path, outcome, started, failed=False)
        finally:
            request_id_var.reset(request_token)
            user_id_var.reset(user_token)


def _incoming_request_id(scope) -> str | None:
    """Reuse a caller-supplied id so a trace survives across services."""
    for name, value in scope.get("headers", []):
        if name.decode().lower() == REQUEST_ID_HEADER:
            candidate = value.decode().strip()
            # Bounded and printable: this value reaches the log unmodified.
            if candidate and len(candidate) <= 128 and candidate.isprintable():
                return candidate
    return None


def _resolve_user_id(scope) -> int | None:
    """Read the authenticated user recorded by the auth dependencies.

    The scope is checked first: FastAPI runs sync dependencies in a worker
    thread, so a ContextVar set inside `get_current_user` never reaches this
    frame. The ContextVar remains the fallback for anything setting it from
    async code in this same context.
    """
    scoped = scope.get("state", {}).get("user_id")
    return scoped if scoped is not None else user_id_var.get()


def _emit(scope, path: str, outcome: dict, started: float, *, failed: bool) -> None:
    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    fields: dict[str, object] = {
        "path": path,
        "duration_ms": duration_ms,
        "user_id": _resolve_user_id(scope),
    }

    if scope["type"] == "websocket":
        fields["protocol"] = "websocket"
        fields["accepted"] = outcome.get("accepted", False)
        fields["close_code"] = outcome.get("close_code")
        message = "websocket closed"
    else:
        fields["method"] = scope.get("method")
        fields["status"] = outcome.get("status", 500 if failed else None)
        message = "request failed" if failed else "request completed"

    if failed:
        logger.exception(message, extra=fields)
    else:
        logger.info(message, extra=fields)
