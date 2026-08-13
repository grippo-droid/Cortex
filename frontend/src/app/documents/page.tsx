"use client";

import { RequireAuth } from "@/components/RequireAuth";
import { useAuth } from "@/lib/auth";

function DocumentsView() {
  const { user, logout } = useAuth();

  return (
    <main className="flex-1 p-8">
      <header className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Documents</h1>
          <p className="mt-1 text-sm opacity-60">
            Signed in as {user?.email}
          </p>
        </div>
        <button
          type="button"
          onClick={logout}
          className="rounded-md border border-black/15 px-3 py-1.5 text-sm transition-opacity hover:opacity-70 dark:border-white/20"
        >
          Sign out
        </button>
      </header>

      <p className="mt-8 text-sm opacity-60">Document dashboard arrives in T2.6.</p>
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
