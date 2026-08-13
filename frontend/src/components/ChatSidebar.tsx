"use client";

import Link from "next/link";

import type { ChatSessionRead } from "@/types";

interface Props {
  sessions: ChatSessionRead[];
  activeSessionId: number | null;
  isLoading: boolean;
  onCreate: () => void;
  onDelete: (session: ChatSessionRead) => void;
}

export function ChatSidebar({
  sessions,
  activeSessionId,
  isLoading,
  onCreate,
  onDelete,
}: Props) {
  return (
    <aside className="flex w-64 shrink-0 flex-col border-r border-black/10 dark:border-white/15">
      <div className="p-3">
        <button
          type="button"
          onClick={onCreate}
          className="w-full rounded-md bg-foreground px-3 py-2 text-sm font-medium text-background transition-opacity hover:opacity-90"
        >
          New chat
        </button>
      </div>

      <nav className="flex-1 overflow-y-auto px-2 pb-3">
        {isLoading ? (
          <p className="px-2 text-xs opacity-60">Loading...</p>
        ) : sessions.length === 0 ? (
          <p className="px-2 text-xs opacity-60">No conversations yet.</p>
        ) : (
          <ul className="space-y-1">
            {sessions.map((session) => {
              const isActive = session.id === activeSessionId;

              return (
                <li key={session.id} className="group relative">
                  <Link
                    href={`/chat/${session.id}`}
                    data-testid="session-link"
                    className={`block truncate rounded-md px-2 py-1.5 pr-8 text-sm transition-colors ${
                      isActive
                        ? "bg-black/10 dark:bg-white/15"
                        : "hover:bg-black/5 dark:hover:bg-white/10"
                    }`}
                  >
                    {session.title}
                  </Link>
                  <button
                    type="button"
                    onClick={() => onDelete(session)}
                    aria-label={`Delete ${session.title}`}
                    className="absolute right-1.5 top-1/2 hidden -translate-y-1/2 rounded px-1.5 py-0.5 text-xs opacity-70 hover:opacity-100 group-hover:block"
                  >
                    &times;
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </nav>
    </aside>
  );
}
