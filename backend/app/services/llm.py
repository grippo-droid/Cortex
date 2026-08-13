"""Chat completion providers.

Same shape as the embedding providers: a small protocol, one implementation per
backend, selected by `CHAT_PROVIDER`. Groq's API is OpenAI-compatible, so both
run through the OpenAI client with a different base URL and model. They are kept
as separate classes so their models and error handling can diverge later.

Unlike embeddings, switching chat provider is free. Nothing generated is stored
in the vector store, so there is no re-embedding and no re-upload.
"""

import random
import time
from collections.abc import Iterator
from typing import Protocol

from app.config import settings

GROQ_BASE_URL = "https://api.groq.com/openai/v1"


class ChatError(Exception):
    """The provider could not produce a completion.

    `transient` marks failures worth retrying: rate limits, upstream 5xx, and
    connection problems. A rejected key or an over-long prompt will fail exactly
    the same way on a second attempt.
    """

    def __init__(self, message: str, *, transient: bool = False) -> None:
        super().__init__(message)
        self.transient = transient


class ChatProvider(Protocol):
    def stream(self, messages: list[dict[str, str]]) -> Iterator[str]:
        """Yield answer fragments in order as they arrive."""
        ...


def _translate(exc: Exception) -> ChatError:
    """Turn a provider exception into something a user can act on."""
    status = getattr(exc, "status_code", None)

    if status == 401:
        return ChatError(
            "The chat provider rejected the API key. Check CHAT_PROVIDER and the "
            "matching key in .env."
        )
    if status == 429:
        return ChatError(
            "The chat provider is rate limiting or out of quota. Try again shortly.",
            transient=True,
        )
    if status == 400 and "context" in str(exc).lower():
        return ChatError(
            "The question and its context were too long for the model. Try a "
            "shorter question."
        )
    if status is not None and status >= 500:
        return ChatError(
            "The chat provider is temporarily unavailable.", transient=True
        )

    # Connection resets, DNS failures, and read timeouts arrive without a status.
    return ChatError(str(exc) or "The chat provider failed.", transient=status is None)


class _OpenAICompatibleChatProvider:
    def __init__(self, api_key: str, model: str, base_url: str | None = None) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url
        self._client = None

    def _get_client(self):
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(
                api_key=self._api_key,
                base_url=self._base_url,
                timeout=settings.llm_timeout_seconds,
                # Retries are handled here rather than in the SDK, because only
                # a failure before the first token may be retried.
                max_retries=0,
            )

        return self._client

    def stream(self, messages: list[dict[str, str]]) -> Iterator[str]:
        try:
            stream = self._get_client().chat.completions.create(
                model=self._model,
                messages=messages,
                stream=True,
                temperature=settings.llm_temperature,
            )
        except Exception as exc:
            raise _translate(exc) from exc

        try:
            for event in stream:
                if not event.choices:
                    continue
                fragment = event.choices[0].delta.content
                if fragment:
                    yield fragment
        except Exception as exc:
            raise _translate(exc) from exc


class GroqChatProvider(_OpenAICompatibleChatProvider):
    def __init__(self, api_key: str, model: str) -> None:
        super().__init__(api_key=api_key, model=model, base_url=GROQ_BASE_URL)


class OpenAIChatProvider(_OpenAICompatibleChatProvider):
    pass


_provider: ChatProvider | None = None


def set_chat_provider(provider: ChatProvider | None) -> None:
    """Swap the provider. Used by the tests to avoid live API calls."""
    global _provider
    _provider = provider


def build_provider(name: str) -> ChatProvider:
    if name == "groq":
        if not settings.groq_api_key:
            raise ChatError(
                "CHAT_PROVIDER is 'groq' but GROQ_API_KEY is not set."
            )
        return GroqChatProvider(
            api_key=settings.groq_api_key, model=settings.groq_chat_model
        )

    if name == "openai":
        if not settings.openai_api_key:
            raise ChatError(
                "CHAT_PROVIDER is 'openai' but OPENAI_API_KEY is not set."
            )
        return OpenAIChatProvider(
            api_key=settings.openai_api_key, model=settings.chat_model
        )

    raise ChatError(f"Unknown CHAT_PROVIDER '{name}'.")


def get_chat_provider() -> ChatProvider:
    global _provider

    if _provider is None:
        _provider = build_provider(settings.chat_provider)

    return _provider


def stream_completion(
    messages: list[dict[str, str]], provider: ChatProvider | None = None
) -> Iterator[str]:
    """Stream an answer, retrying transient failures before the first token.

    Retrying after tokens have been delivered would repeat text the user has
    already read, so once anything has been yielded a failure is final.
    """
    active = provider or get_chat_provider()
    delay = settings.llm_retry_base_seconds

    for attempt in range(1, settings.llm_max_attempts + 1):
        produced = False

        try:
            for fragment in active.stream(messages):
                produced = True
                yield fragment
            return
        except ChatError as error:
            last_attempt = attempt == settings.llm_max_attempts
            if produced or last_attempt or not error.transient:
                raise

        # Jitter so several sockets failing together do not retry in lockstep.
        time.sleep(delay + random.uniform(0, delay / 2))
        delay *= 2
