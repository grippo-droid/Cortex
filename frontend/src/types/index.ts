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

export interface TokenResponse {
  access_token: string;
  token_type: "bearer";
}
