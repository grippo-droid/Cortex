/**
 * Thin fetch wrapper for the Cortex API.
 *
 * The auth context registers a token getter and a 401 handler at mount via
 * `configureApiAuth`, so callers do not have to thread the token through by
 * hand. Passing `token` explicitly still overrides it.
 */

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

interface ApiAuth {
  getToken: () => string | null;
  onUnauthorized: () => void;
}

let apiAuth: ApiAuth | null = null;

export function configureApiAuth(auth: ApiAuth | null): void {
  apiAuth = auth;
}

type RequestOptions = Omit<RequestInit, "body"> & {
  body?: unknown;
  token?: string | null;
  /**
   * Whether a 401 should be treated as an expired session. Login and register
   * opt out: a rejected sign-in is a form error, not a session to tear down.
   */
  handleUnauthorized?: boolean;
};

/** FastAPI returns `detail` as a string, or as a list of errors for a 422. */
async function readErrorMessage(response: Response): Promise<string> {
  try {
    const data: unknown = await response.json();
    const detail = (data as { detail?: unknown })?.detail;

    if (typeof detail === "string") {
      return detail;
    }
    if (Array.isArray(detail)) {
      const first = detail[0] as { msg?: string } | undefined;
      if (first?.msg) {
        return first.msg;
      }
    }
  } catch {
    // Body was not JSON; fall through to the status line.
  }

  return response.statusText || "Request failed";
}

export async function apiFetch<T>(
  path: string,
  {
    body,
    token,
    headers,
    handleUnauthorized = true,
    ...init
  }: RequestOptions = {},
): Promise<T> {
  const bearer = token !== undefined ? token : (apiAuth?.getToken() ?? null);

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      ...(bearer ? { Authorization: `Bearer ${bearer}` } : {}),
      ...headers,
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (!response.ok) {
    const message = await readErrorMessage(response);

    if (response.status === 401 && handleUnauthorized) {
      apiAuth?.onUnauthorized();
    }

    throw new ApiError(response.status, message);
  }

  return response.status === 204 ? (undefined as T) : ((await response.json()) as T);
}
