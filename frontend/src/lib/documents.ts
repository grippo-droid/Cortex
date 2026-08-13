/** Document API calls. Ownership is enforced server-side from the bearer token. */

import { apiFetch } from "@/lib/api";
import type { DocumentRead } from "@/types";

export function listDocuments(): Promise<DocumentRead[]> {
  return apiFetch<DocumentRead[]>("/documents");
}

export function uploadFile(file: File): Promise<DocumentRead> {
  const form = new FormData();
  form.append("file", file);

  return apiFetch<DocumentRead>("/documents", { method: "POST", body: form });
}

export function uploadText(text: string): Promise<DocumentRead> {
  const form = new FormData();
  form.append("text", text);

  return apiFetch<DocumentRead>("/documents", { method: "POST", body: form });
}

export function deleteDocument(documentId: number): Promise<void> {
  return apiFetch<void>(`/documents/${documentId}`, { method: "DELETE" });
}
