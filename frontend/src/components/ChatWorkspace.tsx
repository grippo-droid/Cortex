"use client";

import { useRouter } from "next/navigation";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { ChatComposer } from "@/components/ChatComposer";
import { ChatSidebar } from "@/components/ChatSidebar";
import { MessageList } from "@/components/MessageList";
import { RequireAuth } from "@/components/RequireAuth";
import { ThemeToggle } from "@/components/ThemeToggle";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { createSession, deleteSession, listSessions } from "@/lib/chat";
import { useChatSocket } from "@/hooks/useChatSocket";
import type { ChatSessionRead } from "@/types";

const STATUS_LABEL: Record<string, string> = {
  connecting: "Connecting...",
  authenticating: "Connecting...",
  reconnecting: "Reconnecting...",
  error: "Disconnected",
  closed: "Disconnected",
};

function Workspace({ sessionId }: { sessionId: number | null }) {
  const router = useRouter();
  const { user, logout } = useAuth();

  const [sessions, setSessions] = useState<ChatSessionRead[]>([]);
  const [isLoadingSessions, setIsLoadingSessions] = useState(true);
  const [sidebarError, setSidebarError] = useState<string | null>(null);

  const {
    status,
    messages,
    error,
    isStreaming,
    isLoadingHistory,
    sendMessage,
    retryMessage,
  } = useChatSocket(sessionId);

  useEffect(() => {
    let cancelled = false;

    async function loadSessions() {
      try {
        const listed = await listSessions();
        if (!cancelled) setSessions(listed);
      } catch (caught) {
        if (!cancelled) {
          setSidebarError(
            caught instanceof ApiError ? caught.message : "Could not load chats.",
          );
        }
      } finally {
        if (!cancelled) setIsLoadingSessions(false);
      }
    }

    void loadSessions();
    return () => {
      cancelled = true;
    };
  }, []);

  const handleCreate = useCallback(async () => {
    setSidebarError(null);
    try {
      const created = await createSession();
      setSessions((current) => [created, ...current]);
      router.push(`/chat/${created.id}`);
    } catch (caught) {
      setSidebarError(
        caught instanceof ApiError ? caught.message : "Could not start a chat.",
      );
    }
  }, [router]);

  const handleDelete = useCallback(
    async (session: ChatSessionRead) => {
      if (!window.confirm(`Delete "${session.title}"? This cannot be undone.`)) {
        return;
      }

      setSidebarError(null);
      setSessions((current) => current.filter((item) => item.id !== session.id));

      try {
        await deleteSession(session.id);
        if (session.id === sessionId) {
          router.push("/chat");
        }
      } catch (caught) {
        setSessions((current) =>
          [...current, session].sort((a, b) => b.id - a.id),
        );
        setSidebarError(
          caught instanceof ApiError ? caught.message : "Could not delete it.",
        );
      }
    },
    [router, sessionId],
  );

  const statusLabel = STATUS_LABEL[status];

  return (
    <div className="flex flex-1 overflow-hidden">
      <ChatSidebar
        sessions={sessions}
        activeSessionId={sessionId}
        isLoading={isLoadingSessions}
        onCreate={handleCreate}
        onDelete={handleDelete}
      />

      <section className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between gap-4 border-b border-black/10 px-6 py-3 dark:border-white/15">
          <div className="flex items-center gap-4">
            <h1 className="text-lg font-semibold">Chat</h1>
            <Link href="/documents" className="text-sm underline underline-offset-4 opacity-70">
              Documents
            </Link>
          </div>
          <div className="flex items-center gap-3">
            {statusLabel && (
              <span data-testid="connection-status" className="text-xs opacity-60">
                {statusLabel}
              </span>
            )}
            <span className="text-xs opacity-60">{user?.email}</span>
            <ThemeToggle />
            <button
              type="button"
              onClick={logout}
              className="rounded-md border border-black/15 px-2.5 py-1 text-xs transition-opacity hover:opacity-70 dark:border-white/20"
            >
              Sign out
            </button>
          </div>
        </header>

        {(sidebarError || error) && (
          <p
            role="alert"
            className="mx-6 mt-4 rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-700 dark:text-red-300"
          >
            {sidebarError ?? error}
          </p>
        )}

        {sessionId === null ? (
          <div className="flex flex-1 items-center justify-center p-8">
            <p className="max-w-sm text-center text-sm opacity-60">
              Select a conversation, or start a new one to ask questions about
              your documents.
            </p>
          </div>
        ) : (
          <>
            {isLoadingHistory ? (
              <div className="flex-1 p-6 text-sm opacity-60">Loading conversation...</div>
            ) : (
              <MessageList
                messages={messages}
                isStreaming={isStreaming}
                emptyHint="Ask a question about your uploaded documents."
                onRetry={retryMessage}
              />
            )}
            <ChatComposer
              onSend={sendMessage}
              disabled={isStreaming || status === "error"}
            />
          </>
        )}
      </section>
    </div>
  );
}

export function ChatWorkspace({ sessionId }: { sessionId: number | null }) {
  return (
    <RequireAuth>
      <Workspace sessionId={sessionId} />
    </RequireAuth>
  );
}
