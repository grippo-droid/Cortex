"use client";

import { useEffect, useRef, useState } from "react";

import type { ChatMessage } from "@/types";

/** How close to the bottom still counts as "following the conversation". */
const STICK_THRESHOLD_PX = 50;

function SourceList({ message }: { message: ChatMessage }) {
  const sources = message.sources ?? [];
  if (sources.length === 0) {
    return null;
  }

  return (
    <details className="mt-2 text-xs opacity-70">
      <summary className="cursor-pointer select-none">
        {sources.length} source{sources.length === 1 ? "" : "s"}
      </summary>
      <ul className="mt-1 space-y-1">
        {sources.map((source, index) => (
          <li key={`${source.document_id}-${source.chunk_index}-${index}`}>
            <span className="font-medium">[{index + 1}]</span>{" "}
            {source.filename ?? "document"}
            {source.chunk_index !== null && ` (chunk ${source.chunk_index})`}
          </li>
        ))}
      </ul>
    </details>
  );
}

function Bubble({
  message,
  onRetry,
}: {
  message: ChatMessage;
  onRetry?: (id: string) => void;
}) {
  const isUser = message.role === "user";
  const isPending = message.status === "pending";
  const hasFailed = message.status === "failed";

  return (
    <div className={`flex flex-col ${isUser ? "items-end" : "items-start"}`}>
      <div
        className={`max-w-[80ch] rounded-lg px-4 py-2.5 text-sm ${
          isUser
            ? "bg-foreground text-background"
            : "border border-black/10 dark:border-white/15"
        } ${hasFailed ? "opacity-50 ring-1 ring-red-500/50" : ""} ${
          // Dimmed while unacknowledged, so "shown" is never mistaken for
          // "delivered".
          isPending ? "opacity-60" : ""
        }`}
        // Reserve a line's height the moment the bubble appears, so the first
        // token does not shove the layout down as it arrives.
        style={!isUser && message.status === "streaming" ? { minHeight: "2.75rem" } : undefined}
      >
        <p className="whitespace-pre-wrap break-words">
          {message.content}
          {message.status === "streaming" && (
            <span className="ml-0.5 inline-block h-4 w-1.5 translate-y-0.5 animate-pulse bg-current align-baseline" />
          )}
        </p>

        {message.status === "partial" && (
          <p className="mt-2 text-xs italic opacity-70">
            This answer was cut short.
          </p>
        )}

        {!isUser && <SourceList message={message} />}
      </div>

      {isPending && (
        <span className="mt-1 text-xs opacity-50" data-testid="message-pending">
          Sending...
        </span>
      )}

      {hasFailed && (
        <span
          className="mt-1 flex items-center gap-2 text-xs text-red-600 dark:text-red-400"
          data-testid="message-failed"
        >
          Not sent.
          {onRetry && (
            <button
              type="button"
              onClick={() => onRetry(message.id)}
              data-testid="message-retry"
              className="underline underline-offset-2 hover:opacity-70"
            >
              Retry
            </button>
          )}
        </span>
      )}
    </div>
  );
}

interface Props {
  messages: ChatMessage[];
  isStreaming: boolean;
  emptyHint: string;
  onRetry?: (id: string) => void;
}

export function MessageList({ messages, isStreaming, emptyHint, onRetry }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const stickToBottomRef = useRef(true);
  const [showJump, setShowJump] = useState(false);

  function handleScroll() {
    const element = containerRef.current;
    if (!element) return;

    const distance =
      element.scrollHeight - element.scrollTop - element.clientHeight;
    const atBottom = distance < STICK_THRESHOLD_PX;

    stickToBottomRef.current = atBottom;
    setShowJump(!atBottom);
  }

  function jumpToLatest() {
    const element = containerRef.current;
    if (!element) return;

    element.scrollTop = element.scrollHeight;
    stickToBottomRef.current = true;
    setShowJump(false);
  }

  // Follow new content only while the reader is already at the bottom. Scrolling
  // up mid-answer should not be undone on the next token.
  useEffect(() => {
    if (stickToBottomRef.current && containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [messages]);

  return (
    <div className="relative flex-1 overflow-hidden">
      <div
        ref={containerRef}
        onScroll={handleScroll}
        data-testid="message-list"
        // overflow-anchor is disabled so the browser's own scroll anchoring
        // does not fight the effect above while content grows.
        className="h-full space-y-4 overflow-y-auto p-6 [overflow-anchor:none]"
      >
        {messages.length === 0 ? (
          <p className="mt-10 text-center text-sm opacity-60">{emptyHint}</p>
        ) : (
          messages.map((message) => (
            <Bubble key={message.id} message={message} onRetry={onRetry} />
          ))
        )}

        {isStreaming && messages.at(-1)?.status !== "streaming" && (
          <p className="text-sm opacity-60">Thinking...</p>
        )}
      </div>

      {showJump && (
        <button
          type="button"
          onClick={jumpToLatest}
          className="absolute bottom-4 left-1/2 -translate-x-1/2 rounded-full border border-black/15 bg-background px-3 py-1.5 text-xs shadow-sm dark:border-white/20"
        >
          Jump to latest
        </button>
      )}
    </div>
  );
}
