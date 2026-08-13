"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { useAuth } from "@/lib/auth";

/**
 * Route guard for protected pages.
 *
 * Renders nothing until the stored token has been checked, otherwise every
 * refresh would flash the login redirect while /auth/me is still in flight.
 */
export function RequireAuth({ children }: { children: React.ReactNode }) {
  const { user, isLoading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!isLoading && !user) {
      router.replace("/login");
    }
  }, [isLoading, user, router]);

  if (isLoading) {
    return (
      <main className="flex flex-1 items-center justify-center p-8">
        <p className="text-sm opacity-60">Loading...</p>
      </main>
    );
  }

  if (!user) {
    return null;
  }

  return <>{children}</>;
}
