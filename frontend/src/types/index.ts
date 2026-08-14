/** Shared API types. Mirrors the backend schemas in `backend/app/schemas/`. */

export type DocumentStatus = "pending" | "processing" | "ready" | "failed";

export type MessageRole = "user" | "assistant";

export interface UserRead {
  id: number;
  email: string;
  created_at: string;
}

export interface DocumentRead {
  id: number;
  filename: string;
  uploaded_at: string;
  chunk_count: number;
  status: DocumentStatus;
  /** Why ingestion failed. Only set when `status` is `failed`. */
  error?: string | null;
}

export interface ChatSessionRead {
  id: number;
  title: string;
  created_at: string;
}

export interface MessageRead {
  id: number;
  role: MessageRole;
  content: string;
  created_at: string;
}

/** Returned by both POST /auth/register and POST /auth/login. */
export interface AuthResponse {
  access_token: string;
  token_type: "bearer";
  user: UserRead;
}

export interface SourceChunk {
  content: string;
  filename: string | null;
  document_id: number | null;
  chunk_index: number | null;
  distance: number | null;
}

/** Frames the server sends over the chat socket. */
export type ServerFrame =
  | { type: "ready"; session_id: number }
  | { type: "sources"; chunks: SourceChunk[] }
  | { type: "start" }
  | { type: "token"; content: string }
  | { type: "done"; content: string; partial: boolean }
  | { type: "answer"; content: string; done: boolean }
  | { type: "error"; detail: string };

/**
 * The socket has two ready states and only the second is usable: `open` means
 * the transport connected, `ready` means the server accepted the auth frame.
 */
export type ChatSocketStatus =
  | "idle"
  | "connecting"
  | "authenticating"
  | "ready"
  | "reconnecting"
  | "closed"
  | "error";

/**
 * `pending` is an optimistic question the server has not acknowledged yet;
 * `failed` is one the connection died before delivering, which the user can
 * retry.
 */
export type ChatMessageStatus =
  | "pending"
  | "complete"
  | "streaming"
  | "partial"
  | "failed";

export interface ChatMessage {
  /** Stable for the message's whole life, including while streaming. */
  id: string;
  role: MessageRole;
  content: string;
  status: ChatMessageStatus;
  sources?: SourceChunk[];
}
