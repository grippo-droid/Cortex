"use client";

/**
 * WebSocket hook for the chat stream.
 *
 * Four things here are easy to get wrong and are handled deliberately:
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
 *
 * 4. A question is shown before the server has acknowledged it, so every
 *    optimistic message has to be reconciled. It stays `pending` until the
 *    server's `sources` frame proves the question was accepted, and becomes
 *    `failed` if the connection dies first. Optimism without that second half
 *    leaves a message that was never delivered looking exactly like one that
 *    was.
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

/** A question waiting for the socket to be ready to carry it. */
interface QueuedMessage {
  id: string;
  payload: string;
}

/**
 * Whether a question has left the browser. A message that was only ever queued
 * cannot exist on the server, so it is always kept on a history reload; one
 * that was sent may have been stored before the connection dropped, so it is
 * reconciled against the transcript instead.
 */
type Delivery = "queued" | "sent";

interface UseChatSocket {
  status: ChatSocketStatus;
  messages: ChatMessage[];
  error: string | null;
  isStreaming: boolean;
  isLoadingHistory: boolean;
  sendMessage: (content: string) => void;
  retryMessage: (id: string) => void;
}

export function useChatSocket(sessionId: number | null): UseChatSocket {
  const { token } = useAuth();

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [status, setStatus] = useState<ChatSocketStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const [isLoadingHistory, setIsLoadingHistory] = useState(false);
  // Bumped by a retry after the socket has gone terminal, to re-run the
  // connection effect. Retrying is the one way back from "error" without a
  // page reload.
  const [reconnectNonce, setReconnectNonce] = useState(0);

  const socketRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const attemptsRef = useRef(0);
  const shouldReconnectRef = useRef(true);
  const hasConnectedRef = useRef(false);
  /**
   * The socket has stopped for good and will not retry on its own: either the
   * server refused with 1008, or the backoff ladder ran out. Tracked separately
   * from `shouldReconnectRef`, which stays true here because it only marks
   * teardown, so a retry cannot use it to tell whether a reconnect is needed.
   */
  const isTerminalRef = useRef(false);
  /** Which session the queue below belongs to. */
  const preparedSessionRef = useRef<number | null>(null);

  const queuedRef = useRef<QueuedMessage[]>([]);
  const deliveryRef = useRef<Map<string, Delivery>>(new Map());
  // Whether the server has accepted the auth frame. Held in a ref rather than
  // read from state so `sendMessage` never acts on a stale closure, and only
  // ever written from callbacks.
  const isReadyRef = useRef(false);

  // Mirrors `messages` so `retryMessage` can read a message's text without
  // taking a dependency on the array and rebuilding on every token.
  const messagesRef = useRef<ChatMessage[]>([]);
  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  // Streaming accumulation.
  const streamingIdRef = useRef<string | null>(null);
  const pendingTextRef = useRef("");
  const frameRef = useRef<number | null>(null);
  const sourcesRef = useRef<SourceChunk[]>([]);

  const loadHistory = useCallback(async (id: number) => {
    setIsLoadingHistory(true);
    try {
      const stored = await listMessages(id);

      setMessages((current) => {
        // The server transcript is the truth for anything it has stored, but it
        // knows nothing about questions still queued or already failed. Dropping
        // those here would erase a question the user can still retry.
        const undelivered = current.filter(
          (message) => message.status === "pending" || message.status === "failed",
        );

        // A question that was actually sent may have been stored just before the
        // connection dropped, in which case the transcript already contains it.
        // Consume one stored copy per sent message so it is not shown twice.
        const storedUserCounts = new Map<string, number>();
        for (const message of stored) {
          if (message.role === "user") {
            storedUserCounts.set(
              message.content,
              (storedUserCounts.get(message.content) ?? 0) + 1,
            );
          }
        }

        const kept = undelivered.filter((message) => {
          if (deliveryRef.current.get(message.id) !== "sent") {
            return true;
          }
          const remaining = storedUserCounts.get(message.content) ?? 0;
          if (remaining > 0) {
            storedUserCounts.set(message.content, remaining - 1);
            deliveryRef.current.delete(message.id);
            return false;
          }
          return true;
        });

        return [
          ...stored.map((message) => ({
            id: `stored-${message.id}`,
            role: message.role,
            content: message.content,
            status: "complete" as const,
          })),
          ...kept,
        ];
      });
    } catch {
      setError("Could not load this conversation.");
    } finally {
      setIsLoadingHistory(false);
    }
  }, []);

  /** Settle the oldest question still awaiting acknowledgement. */
  const settleOldestPending = useCallback((next: "complete" | "failed") => {
    setMessages((current) => {
      const index = current.findIndex((message) => message.status === "pending");
      if (index === -1) {
        return current;
      }

      if (next === "complete") {
        deliveryRef.current.delete(current[index].id);
      }

      const updated = [...current];
      updated[index] = { ...updated[index], status: next };
      return updated;
    });
  }, []);

  /**
   * Give up on every question still in flight. Called only when the socket has
   * gone terminal, so nothing is left waiting on a connection that is not
   * coming back. The queue is dropped at the same time, since its entries are
   * exactly the messages being failed.
   */
  const failAllPending = useCallback(() => {
    queuedRef.current = [];
    setMessages((current) =>
      current.map((message) =>
        message.status === "pending"
          ? { ...message, status: "failed" as const }
          : message,
      ),
    );
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
          queued.forEach((item) => {
            socketRef.current?.send(item.payload);
            deliveryRef.current.set(item.id, "sent");
          });
          break;
        }

        case "sources":
          // The server only reaches this point once it has accepted the
          // question, so it is the acknowledgement the optimistic bubble waits
          // for.
          sourcesRef.current = frame.chunks;
          settleOldestPending("complete");
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
          } else {
            // No stream in progress means the question was rejected before the
            // server began answering it, so it never became part of the
            // conversation.
            settleOldestPending("failed");
          }
          break;
      }
    },
    [finishStream, loadHistory, scheduleFlush, sessionId, settleOldestPending],
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
          isTerminalRef.current = true;
          setStatus("error");
          setError("This conversation is not available.");
          failAllPending();
          return;
        }

        attemptsRef.current += 1;
        if (attemptsRef.current > MAX_RECONNECT_ATTEMPTS) {
          isTerminalRef.current = true;
          setStatus("error");
          setError("Lost connection to the server. Try again, or reload.");
          failAllPending();
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
      isTerminalRef.current = false;
      setError(null);

      // Only discard queued messages when moving to a different conversation.
      // Clearing unconditionally loses a question typed while the socket was
      // still connecting, because React Strict Mode runs this twice on mount
      // and the second run would wipe what the first had queued.
      if (preparedSessionRef.current !== sessionId) {
        queuedRef.current = [];
        deliveryRef.current.clear();
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
  }, [
    sessionId,
    token,
    handleFrame,
    finishStream,
    loadHistory,
    failAllPending,
    reconnectNonce,
  ]);

  /** Send `payload`, or hold it until the server is ready to accept it. */
  const dispatch = useCallback((id: string, payload: string) => {
    const socket = socketRef.current;

    if (socket?.readyState === WebSocket.OPEN && isReadyRef.current) {
      socket.send(payload);
      deliveryRef.current.set(id, "sent");
      return true;
    }

    // Not authorised yet: hold it rather than let the server discard it.
    queuedRef.current.push({ id, payload });
    deliveryRef.current.set(id, "queued");
    return false;
  }, []);

  const sendMessage = useCallback(
    (content: string) => {
      const trimmed = content.trim();
      if (!trimmed) {
        return;
      }

      setError(null);

      // Optimistic: the question appears before any acknowledgement, but as
      // `pending` rather than `complete`. It is settled by the server's
      // `sources` frame, or failed if the connection dies first.
      const id = nextId("user");
      setMessages((current) => [
        ...current,
        { id, role: "user", content: trimmed, status: "pending" },
      ]);

      dispatch(id, JSON.stringify({ type: "message", content: trimmed }));
    },
    [dispatch],
  );

  const retryMessage = useCallback(
    (id: string) => {
      const message = messagesRef.current.find((item) => item.id === id);
      if (!message || message.status !== "failed") {
        return;
      }

      setError(null);
      setMessages((current) =>
        current.map((item) =>
          item.id === id ? { ...item, status: "pending" as const } : item,
        ),
      );

      const queuedOnly = !dispatch(
        id,
        JSON.stringify({ type: "message", content: message.content }),
      );

      // A terminal socket will never drain the queue on its own, so retrying
      // from "error" has to restart the connection as well. Without this the
      // message re-queues against a socket that is never coming back and sits
      // pending for ever.
      if (queuedOnly && isTerminalRef.current) {
        setReconnectNonce((value) => value + 1);
      }
    },
    [dispatch],
  );

  return {
    status,
    messages,
    error,
    isStreaming,
    isLoadingHistory,
    sendMessage,
    retryMessage,
  };
}
