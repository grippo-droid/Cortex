/** Chat session REST calls. Ownership is enforced server-side from the token. */

import { apiFetch } from "@/lib/api";
import type { ChatSessionRead, MessageRead } from "@/types";

export function listSessions(): Promise<ChatSessionRead[]> {
  return apiFetch<ChatSessionRead[]>("/chat/sessions");
}

export function createSession(title?: string): Promise<ChatSessionRead> {
  return apiFetch<ChatSessionRead>("/chat/sessions", {
    method: "POST",
    body: title ? { title } : {},
  });
}

export function deleteSession(sessionId: number): Promise<void> {
  return apiFetch<void>(`/chat/sessions/${sessionId}`, { method: "DELETE" });
}

export function listMessages(sessionId: number): Promise<MessageRead[]> {
  return apiFetch<MessageRead[]>(`/chat/sessions/${sessionId}/messages`);
}
