"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { DocumentList, type PendingUpload } from "@/components/DocumentList";
import { DocumentUpload } from "@/components/DocumentUpload";
import { RequireAuth } from "@/components/RequireAuth";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import {
  deleteDocument,
  listDocuments,
  uploadFile,
  uploadText,
} from "@/lib/documents";
import { validateUploadFile } from "@/lib/validation";
import type { DocumentRead } from "@/types";

function describe(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

function DocumentsView() {
  const { user, logout } = useAuth();

  const [documents, setDocuments] = useState<DocumentRead[]>([]);
  const [pending, setPending] = useState<PendingUpload[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const listed = await listDocuments();
        if (!cancelled) setDocuments(listed);
      } catch (caught) {
        if (!cancelled) {
          setError(describe(caught, "Could not load your documents."));
        }
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  /** Runs one upload with an optimistic row, returning true on success. */
  const runUpload = useCallback(
    async (label: string, send: () => Promise<DocumentRead>): Promise<boolean> => {
      const tempId = `${label}-${Date.now()}-${Math.random()}`;
      setPending((current) => [...current, { tempId, filename: label }]);

      try {
        const created = await send();
        setDocuments((current) => [created, ...current]);
        return true;
      } catch (caught) {
        setError(describe(caught, `Could not upload "${label}".`));
        return false;
      } finally {
        setPending((current) => current.filter((item) => item.tempId !== tempId));
      }
    },
    [],
  );

  const handleFiles = useCallback(
    async (files: File[]) => {
      setError(null);

      // Sequential rather than parallel: one failure then reports against its
      // own file instead of being lost among concurrent errors.
      for (const file of files) {
        const invalid = validateUploadFile(file);

        if (invalid) {
          setError(invalid);
          continue;
        }

        await runUpload(file.name, () => uploadFile(file));
      }
    },
    [runUpload],
  );

  const handleText = useCallback(
    async (text: string) => {
      setError(null);
      await runUpload("pasted text", () => uploadText(text));
    },
    [runUpload],
  );

  const handleDelete = useCallback(async (document: DocumentRead) => {
    if (!window.confirm(`Delete "${document.filename}"? This cannot be undone.`)) {
      return;
    }

    setError(null);
    // Optimistic removal, restored below if the request fails.
    setDocuments((current) => current.filter((item) => item.id !== document.id));

    try {
      await deleteDocument(document.id);
    } catch (caught) {
      setDocuments((current) =>
        [...current, document].sort((a, b) => b.id - a.id),
      );
      setError(describe(caught, `Could not delete "${document.filename}".`));
    }
  }, []);

  return (
    <main className="mx-auto w-full max-w-3xl flex-1 space-y-6 p-8">
      <header className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Documents</h1>
          <p className="mt-1 text-sm opacity-60">Signed in as {user?.email}</p>
        </div>
        <div className="flex items-center gap-3">
          <Link href="/chat" className="text-sm underline underline-offset-4 opacity-70">
            Chat
          </Link>
          <button
            type="button"
            onClick={logout}
            className="rounded-md border border-black/15 px-3 py-1.5 text-sm transition-opacity hover:opacity-70 dark:border-white/20"
          >
            Sign out
          </button>
        </div>
      </header>

      <DocumentUpload
        onFilesSelected={handleFiles}
        onTextSubmit={handleText}
        disabled={pending.length > 0}
      />

      {error && (
        <p
          role="alert"
          className="rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-700 dark:text-red-300"
        >
          {error}
        </p>
      )}

      {isLoading ? (
        <p className="text-sm opacity-60">Loading documents...</p>
      ) : (
        <DocumentList
          documents={documents}
          pending={pending}
          onDelete={handleDelete}
        />
      )}
    </main>
  );
}

export default function DocumentsPage() {
  return (
    <RequireAuth>
      <DocumentsView />
    </RequireAuth>
  );
}
