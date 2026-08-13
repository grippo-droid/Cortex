"use client";

/**
 * WebSocket hook for the chat stream.
 *
 * Three things here are easy to get wrong and are handled deliberately:
 *
 * 1. The socket has two ready states. `onopen` means "the transport connected,
 *    send the auth frame now", not "the server will accept messages". Anything
 *    typed before the server's `ready` frame is queued, because a message sent
 *    to an unauthenticated socket is silently discarded.
 *
 * 2. A 1008 close is terminal. It means the token was rejected or the session
 *    is not the caller's, and reconnecting would loop forever against a
 *    decision that will not change. Every other close is retried with backoff.
 *
 * 3. Tokens arrive far faster than the screen refreshes. They accumulate in a
 *    ref and flush once per animation frame, so a 500-token answer costs about
 *    60 renders a second rather than 300.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { API_BASE_URL } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { listMessages } from "@/lib/chat";
import type {
  ChatMessage,
  ChatSocketStatus,
  ServerFrame,
  SourceChunk,
} from "@/types";

const WS_BASE_URL = API_BASE_URL.replace(/^http/, "ws");

const MAX_RECONNECT_ATTEMPTS = 6;
const BASE_RECONNECT_DELAY_MS = 1000;
const MAX_RECONNECT_DELAY_MS = 15000;

/** Close code the server uses for a rejected token or a session that is not yours. */
const POLICY_VIOLATION = 1008;

let messageCounter = 0;
function nextId(prefix: string): string {
  messageCounter += 1;
  return `${prefix}-${messageCounter}`;
}

interface UseChatSocket {
  status: ChatSocketStatus;
  messages: ChatMessage[];
  error: string | null;
  isStreaming: boolean;
  isLoadingHistory: boolean;
  sendMessage: (content: string) => void;
}

export function useChatSocket(sessionId: number | null): UseChatSocket {
  const { token } = useAuth();

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [status, setStatus] = useState<ChatSocketStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const [isLoadingHistory, setIsLoadingHistory] = useState(false);

  const socketRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const attemptsRef = useRef(0);
  const shouldReconnectRef = useRef(true);
  const hasConnectedRef = useRef(false);
  /** Which session the queue below belongs to. */
  const preparedSessionRef = useRef<number | null>(null);

  const queuedRef = useRef<string[]>([]);
  // Whether the server has accepted the auth frame. Held in a ref rather than
  // read from state so `sendMessage` never acts on a stale closure, and only
  // ever written from callbacks.
  const isReadyRef = useRef(false);

  // Streaming accumulation.
  const streamingIdRef = useRef<string | null>(null);
  const pendingTextRef = useRef("");
  const frameRef = useRef<number | null>(null);
  const sourcesRef = useRef<SourceChunk[]>([]);

  const loadHistory = useCallback(async (id: number) => {
    setIsLoadingHistory(true);
    try {
      const stored = await listMessages(id);
      setMessages(
        stored.map((message) => ({
          id: `stored-${message.id}`,
          role: message.role,
          content: message.content,
          status: "complete" as const,
        })),
      );
    } catch {
      setError("Could not load this conversation.");
    } finally {
      setIsLoadingHistory(false);
    }
  }, []);

  const flushTokens = useCallback(() => {
    frameRef.current = null;

    const pending = pendingTextRef.current;
    pendingTextRef.current = "";
    if (!pending || !streamingIdRef.current) {
      return;
    }

    const id = streamingIdRef.current;
    setMessages((current) =>
      current.map((message) =>
        message.id === id
          ? { ...message, content: message.content + pending }
          : message,
      ),
    );
  }, []);

  const scheduleFlush = useCallback(() => {
    if (frameRef.current !== null) {
      return;
    }
    frameRef.current = requestAnimationFrame(flushTokens);
  }, [flushTokens]);

  const finishStream = useCallback(
    (content: string | null, nextStatus: ChatMessage["status"]) => {
      if (frameRef.current !== null) {
        cancelAnimationFrame(frameRef.current);
        frameRef.current = null;
      }

      const trailing = pendingTextRef.current;
      pendingTextRef.current = "";
      const id = streamingIdRef.current;
      streamingIdRef.current = null;
      setIsStreaming(false);

      if (!id) {
        return;
      }

      setMessages((current) =>
        current.map((message) =>
          message.id === id
            ? {
                ...message,
                // `done` carries the whole answer, so prefer it over the local
                // concatenation: a dropped frame would otherwise go unnoticed.
                content: content ?? message.content + trailing,
                status: nextStatus,
              }
            : message,
        ),
      );
    },
    [],
  );

  const handleFrame = useCallback(
    (frame: ServerFrame) => {
      switch (frame.type) {
        case "ready": {
          isReadyRef.current = true;
          setStatus("ready");
          setError(null);

          const reconnected = attemptsRef.current > 0;
          attemptsRef.current = 0;

          // After a drop the server's transcript is the truth, including any
          // partial answer it stored while we were away.
          if (reconnected && sessionId !== null) {
            void loadHistory(sessionId);
          }

          const queued = queuedRef.current;
          queuedRef.current = [];
          queued.forEach((payload) => socketRef.current?.send(payload));
          break;
        }

        case "sources":
          sourcesRef.current = frame.chunks;
          break;

        case "start": {
          const id = nextId("assistant");
          streamingIdRef.current = id;
          setIsStreaming(true);
          setMessages((current) => [
            ...current,
            {
              id,
              role: "assistant",
              content: "",
              status: "streaming",
              sources: sourcesRef.current,
            },
          ]);
          break;
        }

        case "token":
          pendingTextRef.current += frame.content;
          scheduleFlush();
          break;

        case "done":
          finishStream(frame.content, frame.partial ? "partial" : "complete");
          break;

        case "answer":
          // The direct reply when retrieval found nothing: complete on arrival.
          setMessages((current) => [
            ...current,
            {
              id: nextId("assistant"),
              role: "assistant",
              content: frame.content,
              status: "complete",
              sources: [],
            },
          ]);
          break;

        case "error":
          setError(frame.detail);
          if (streamingIdRef.current) {
            finishStream(null, "partial");
          }
          break;
      }
    },
    [finishStream, loadHistory, scheduleFlush, sessionId],
  );

  useEffect(() => {
    let disposed = false;

    const connect = () => {
      if (disposed || !shouldReconnectRef.current) {
        return;
      }

      setStatus(attemptsRef.current > 0 ? "reconnecting" : "connecting");

      const socket = new WebSocket(`${WS_BASE_URL}/chat/stream/${sessionId}`);
      socketRef.current = socket;

      socket.onopen = () => {
        hasConnectedRef.current = true;
        // Connected, but not yet authorised: the server ignores anything sent
        // before it has verified this frame.
        setStatus("authenticating");
        socket.send(JSON.stringify({ type: "auth", token }));
      };

      socket.onmessage = (event) => {
        try {
          handleFrame(JSON.parse(event.data) as ServerFrame);
        } catch {
          // A frame we cannot parse is not worth tearing the session down for.
        }
      };

      socket.onclose = (event) => {
        isReadyRef.current = false;

        if (socketRef.current === socket) {
          socketRef.current = null;
        }

        if (streamingIdRef.current) {
          finishStream(null, "partial");
        }

        if (disposed || !shouldReconnectRef.current) {
          setStatus("closed");
          return;
        }

        if (event.code === POLICY_VIOLATION) {
          // Rejected on purpose. Retrying would loop against a fixed decision.
          setStatus("error");
          setError("This conversation is not available.");
          return;
        }

        attemptsRef.current += 1;
        if (attemptsRef.current > MAX_RECONNECT_ATTEMPTS) {
          setStatus("error");
          setError("Lost connection to the server. Reload to try again.");
          return;
        }

        const backoff = Math.min(
          BASE_RECONNECT_DELAY_MS * 2 ** (attemptsRef.current - 1),
          MAX_RECONNECT_DELAY_MS,
        );
        // Jitter so many clients dropped together do not return in lockstep.
        const delay = backoff + Math.random() * (backoff / 2);

        setStatus("reconnecting");
        reconnectTimerRef.current = setTimeout(connect, delay);
      };
    };

    // Wrapped in a function so the state resets below are not synchronous
    // statements in the effect body.
    const start = async () => {
      if (sessionId === null || !token) {
        setMessages([]);
        setStatus("idle");
        return;
      }

      shouldReconnectRef.current = true;
      attemptsRef.current = 0;
      hasConnectedRef.current = false;
      isReadyRef.current = false;
      setError(null);

      // Only discard queued messages when moving to a different conversation.
      // Clearing unconditionally loses a question typed while the socket was
      // still connecting, because React Strict Mode runs this twice on mount
      // and the second run would wipe what the first had queued.
      if (preparedSessionRef.current !== sessionId) {
        queuedRef.current = [];
        preparedSessionRef.current = sessionId;
      }

      await loadHistory(sessionId);
      if (!disposed) {
        connect();
      }
    };

    void start();

    return () => {
      // Runs twice per mount under React Strict Mode in development, so the
      // socket is held in a ref and closed here rather than left dangling.
      disposed = true;
      shouldReconnectRef.current = false;

      if (reconnectTimerRef.current !== null) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      if (frameRef.current !== null) {
        cancelAnimationFrame(frameRef.current);
        frameRef.current = null;
      }

      socketRef.current?.close();
      socketRef.current = null;
      streamingIdRef.current = null;
      pendingTextRef.current = "";
      isReadyRef.current = false;
    };
  }, [sessionId, token, handleFrame, finishStream, loadHistory]);

  const sendMessage = useCallback((content: string) => {
    const trimmed = content.trim();
    if (!trimmed) {
      return;
    }

    setError(null);
    // Optimistic: the question appears before any acknowledgement. The server
    // stores it before generating, so a refresh reconciles to the same thing.
    setMessages((current) => [
      ...current,
      { id: nextId("user"), role: "user", content: trimmed, status: "complete" },
    ]);

    const payload = JSON.stringify({ type: "message", content: trimmed });
    const socket = socketRef.current;

    if (socket?.readyState === WebSocket.OPEN && isReadyRef.current) {
      socket.send(payload);
    } else {
      // Not authorised yet: hold it rather than let the server discard it.
      queuedRef.current.push(payload);
    }
  }, []);

  return { status, messages, error, isStreaming, isLoadingHistory, sendMessage };
}
