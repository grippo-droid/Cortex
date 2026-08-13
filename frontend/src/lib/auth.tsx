"use client";

/**
 * Auth context: token storage, session restore, and the route guard's source
 * of truth.
 *
 * Tokens live in localStorage. That is the fallback the security document
 * permits provided it is disclosed, and it is disclosed in the README: any
 * injected script can read it. The alternatives were an httpOnly cookie, which
 * needs CSRF handling and a cookie-aware WebSocket handshake, or an in-memory
 * variable, which signs the user out on every refresh.
 */

import { useRouter } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import { apiFetch, configureApiAuth } from "@/lib/api";
import type { AuthResponse, UserRead } from "@/types";

const TOKEN_STORAGE_KEY = "cortex.token";

function readStoredToken(): string | null {
  if (typeof window === "undefined") {
    return null;
  }
  return window.localStorage.getItem(TOKEN_STORAGE_KEY);
}

function writeStoredToken(token: string | null): void {
  if (typeof window === "undefined") {
    return;
  }
  if (token === null) {
    window.localStorage.removeItem(TOKEN_STORAGE_KEY);
  } else {
    window.localStorage.setItem(TOKEN_STORAGE_KEY, token);
  }
}

interface AuthContextValue {
  user: UserRead | null;
  token: string | null;
  /** True until the stored token has been checked against the API. */
  isLoading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [user, setUser] = useState<UserRead | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const clearSession = useCallback(() => {
    writeStoredToken(null);
    setToken(null);
    setUser(null);
  }, []);

  // Re-registered whenever the token changes, so the API client always sends
  // the current one without any component threading it through by hand.
  useEffect(() => {
    configureApiAuth({
      getToken: () => token,
      onUnauthorized: () => {
        clearSession();
        router.replace("/login");
      },
    });

    return () => configureApiAuth(null);
  }, [token, clearSession, router]);

  // Restore a session from the stored token. /auth/me is what decides whether
  // that token is still good, so an expired one is cleared here rather than
  // surfacing as a failure on the user's first real action.
  useEffect(() => {
    let cancelled = false;

    async function restoreSession() {
      const stored = readStoredToken();

      if (!stored) {
        if (!cancelled) {
          setIsLoading(false);
        }
        return;
      }

      try {
        const restored = await apiFetch<UserRead>("/auth/me", {
          token: stored,
          handleUnauthorized: false,
        });

        if (!cancelled) {
          setToken(stored);
          setUser(restored);
        }
      } catch {
        if (!cancelled) {
          clearSession();
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    }

    void restoreSession();

    return () => {
      cancelled = true;
    };
  }, [clearSession]);

  const authenticate = useCallback(
    async (path: string, email: string, password: string) => {
      const result = await apiFetch<AuthResponse>(path, {
        method: "POST",
        body: { email, password },
        token: null,
        handleUnauthorized: false,
      });

      writeStoredToken(result.access_token);
      setToken(result.access_token);
      setUser(result.user);
    },
    [],
  );

  const login = useCallback(
    (email: string, password: string) => authenticate("/auth/login", email, password),
    [authenticate],
  );

  const register = useCallback(
    (email: string, password: string) => authenticate("/auth/register", email, password),
    [authenticate],
  );

  const logout = useCallback(() => {
    clearSession();
    router.replace("/login");
  }, [clearSession, router]);

  const value = useMemo(
    () => ({ user, token, isLoading, login, register, logout }),
    [user, token, isLoading, login, register, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);

  if (context === null) {
    throw new Error("useAuth must be used inside an AuthProvider.");
  }

  return context;
}
