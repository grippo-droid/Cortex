"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { ThemeToggle } from "@/components/ThemeToggle";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { validateEmail, validatePassword } from "@/lib/validation";

type Mode = "login" | "register";

const COPY = {
  login: {
    heading: "Sign in to Cortex",
    submit: "Sign in",
    pending: "Signing in...",
    switchPrompt: "Need an account?",
    switchHref: "/register",
    switchLabel: "Create one",
  },
  register: {
    heading: "Create an account",
    submit: "Create account",
    pending: "Creating account...",
    switchPrompt: "Already have an account?",
    switchHref: "/login",
    switchLabel: "Sign in",
  },
} as const;

export function AuthForm({ mode }: { mode: Mode }) {
  const copy = COPY[mode];
  const router = useRouter();
  const { login, register, user, isLoading } = useAuth();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Someone already signed in has no business on these pages.
  useEffect(() => {
    if (!isLoading && user) {
      router.replace("/documents");
    }
  }, [isLoading, user, router]);

  function validate(): string | null {
    return (
      validateEmail(email) ??
      validatePassword(password) ??
      (mode === "register" && password !== confirmPassword
        ? "Passwords do not match."
        : null)
    );
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();

    const validationError = validate();
    if (validationError) {
      setError(validationError);
      return;
    }

    setError(null);
    setIsSubmitting(true);

    try {
      await (mode === "login" ? login : register)(email.trim(), password);
      router.replace("/documents");
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.message
          : "Could not reach the server. Is the API running?",
      );
      setIsSubmitting(false);
    }
  }

  return (
    <main className="relative flex flex-1 items-center justify-center p-8">
      {/* Reachable before signing in, so the preference can be set on the first
          page a new user sees. */}
      <div className="absolute right-6 top-6">
        <ThemeToggle />
      </div>

      <form
        onSubmit={handleSubmit}
        noValidate
        className="w-full max-w-sm space-y-5"
      >
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold">{copy.heading}</h1>
          <p className="text-sm opacity-60">
            Chat with your own documents, and only your own.
          </p>
        </div>

        <label className="block space-y-1.5">
          <span className="text-sm font-medium">Email</span>
          <input
            type="email"
            name="email"
            autoComplete="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            className="w-full rounded-md border border-black/15 bg-transparent px-3 py-2 text-sm outline-none focus:border-black/40 dark:border-white/20 dark:focus:border-white/50"
          />
        </label>

        <label className="block space-y-1.5">
          <span className="text-sm font-medium">Password</span>
          <input
            type="password"
            name="password"
            autoComplete={mode === "login" ? "current-password" : "new-password"}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            className="w-full rounded-md border border-black/15 bg-transparent px-3 py-2 text-sm outline-none focus:border-black/40 dark:border-white/20 dark:focus:border-white/50"
          />
        </label>

        {mode === "register" && (
          <label className="block space-y-1.5">
            <span className="text-sm font-medium">Confirm password</span>
            <input
              type="password"
              name="confirmPassword"
              autoComplete="new-password"
              value={confirmPassword}
              onChange={(event) => setConfirmPassword(event.target.value)}
              className="w-full rounded-md border border-black/15 bg-transparent px-3 py-2 text-sm outline-none focus:border-black/40 dark:border-white/20 dark:focus:border-white/50"
            />
          </label>
        )}

        {error && (
          <p
            role="alert"
            className="rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-700 dark:text-red-300"
          >
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={isSubmitting}
          className="w-full rounded-md bg-foreground px-3 py-2 text-sm font-medium text-background transition-opacity hover:opacity-90 disabled:opacity-50"
        >
          {isSubmitting ? copy.pending : copy.submit}
        </button>

        <p className="text-sm opacity-70">
          {copy.switchPrompt}{" "}
          <Link href={copy.switchHref} className="underline underline-offset-4">
            {copy.switchLabel}
          </Link>
        </p>
      </form>
    </main>
  );
}
