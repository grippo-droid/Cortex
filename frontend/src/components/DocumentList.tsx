"use client";

import type { DocumentRead, DocumentStatus } from "@/types";

export interface PendingUpload {
  tempId: string;
  filename: string;
}

interface Props {
  documents: DocumentRead[];
  pending: PendingUpload[];
  onDelete: (document: DocumentRead) => void;
}

const STATUS_STYLES: Record<DocumentStatus, string> = {
  ready: "bg-green-500/15 text-green-700 dark:text-green-300",
  failed: "bg-red-500/15 text-red-700 dark:text-red-300",
  // Only observable once ingestion moves to a background task in T5.2; the
  // badges are here already so that change needs no frontend work.
  pending: "bg-amber-500/15 text-amber-700 dark:text-amber-300",
  processing: "bg-amber-500/15 text-amber-700 dark:text-amber-300",
};

function formatDate(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime())
    ? value
    : parsed.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function StatusBadge({ status }: { status: DocumentStatus }) {
  const style = STATUS_STYLES[status] ?? "bg-black/10 dark:bg-white/10";

  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${style}`}>
      {status}
    </span>
  );
}

export function DocumentList({ documents, pending, onDelete }: Props) {
  if (documents.length === 0 && pending.length === 0) {
    return (
      <div className="rounded-lg border border-black/10 p-10 text-center dark:border-white/15">
        <h2 className="text-base font-medium">No documents yet</h2>
        <p className="mx-auto mt-1 max-w-sm text-sm opacity-60">
          Upload a document above, then head to the chat to ask questions about
          it. Answers come only from what you have uploaded.
        </p>
      </div>
    );
  }

  return (
    <ul className="divide-y divide-black/10 rounded-lg border border-black/10 dark:divide-white/10 dark:border-white/15">
      {pending.map((item) => (
        <li
          key={item.tempId}
          className="flex items-center justify-between gap-4 p-4 opacity-70"
        >
          <div className="min-w-0">
            <p className="truncate text-sm font-medium">{item.filename}</p>
            <p className="mt-0.5 text-xs opacity-60">Uploading and embedding...</p>
          </div>
          <span className="rounded-full bg-amber-500/15 px-2 py-0.5 text-xs font-medium text-amber-700 dark:text-amber-300">
            uploading
          </span>
        </li>
      ))}

      {documents.map((document) => (
        <li
          key={document.id}
          data-testid="document-row"
          className="flex items-center justify-between gap-4 p-4"
        >
          <div className="min-w-0">
            <p className="truncate text-sm font-medium">{document.filename}</p>
            <p className="mt-0.5 text-xs opacity-60">
              {formatDate(document.uploaded_at)} &middot; {document.chunk_count}{" "}
              {document.chunk_count === 1 ? "chunk" : "chunks"}
            </p>
            {document.status === "failed" && document.error && (
              // Ingestion finishes after the upload response, so this is the
              // only place the reason can reach the user.
              <p
                className="mt-1 text-xs text-red-600 dark:text-red-400"
                data-testid="document-error"
              >
                {document.error}
              </p>
            )}
          </div>

          <div className="flex shrink-0 items-center gap-3">
            <StatusBadge status={document.status} />
            <button
              type="button"
              onClick={() => onDelete(document)}
              aria-label={`Delete ${document.filename}`}
              className="rounded-md border border-black/15 px-2.5 py-1 text-xs transition-opacity hover:opacity-70 dark:border-white/20"
            >
              Delete
            </button>
          </div>
        </li>
      ))}
    </ul>
  );
}
