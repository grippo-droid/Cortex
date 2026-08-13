# Security & Access Document — Cortex

This is the most heavily graded constraint in the assessment: **a user must never be
able to access or query another user's documents or chat history.** Every design
decision below exists to enforce that.

## 1. Authentication
- Passwords hashed with bcrypt (via passlib), never stored or logged in plaintext.
- JWT signed with a server-side secret (`JWT_SECRET` env var), short-ish expiry
  (e.g., 24h), includes `sub` (user id) and `exp`.
- JWT secret and any API keys live only in `.env`, never committed; `.env.example`
  provided with placeholder values.

## 2. Authorization — the core isolation rule
**Rule: every query that touches user data must filter by `user_id` derived from the
verified JWT — never from a client-supplied parameter (body, query string, or path).**

Applies to:
- `GET /documents` — `WHERE user_id = current_user.id`
- `POST /documents` — new rows always written with `user_id = current_user.id`
- `POST /chat/sessions` — session created with `user_id = current_user.id`
- `WS /chat/stream/{session_id}` — before accepting the socket, load the session and
  reject (close with policy-violation code) if `session.user_id != current_user.id`
- Vector search — only ever queries the caller's own Chroma collection/namespace;
  collection name is derived server-side from `user_id`, never accepted from the client

## 3. Testing isolation (do this before submitting)
- Create two users, A and B.
- Upload a document as A. As B, call `GET /documents` and confirm A's doc is absent.
- As B, try `GET /documents/{a_doc_id}` (if such a route exists) and confirm 403/404.
- As B, try to open `WS /chat/stream/{a_session_id}` and confirm rejection.
- As B, ask a question in B's own session that only A's document could answer, and
  confirm the AI does not have access to that content.

## 4. Transport & storage
- HTTPS assumed in front of the app in any real deployment (note as an assumption if
  running locally over HTTP).
- WebSocket auth: pass JWT via query param or an initial auth message immediately after
  connect; do not trust an unauthenticated socket.

## 5. Frontend token handling
- Preferred: httpOnly, secure cookie set by the backend on login (mitigates XSS token
  theft). Acceptable fallback for the prototype: in-memory JS variable, avoided
  `localStorage` where possible since it's readable by any injected script.
- If `localStorage` is used for simplicity, document it explicitly as a known limitation
  in the README.

## 6. Input handling
- Validate uploaded file types/extensions server-side, not just client-side.
- Enforce a max file size.
- Sanitize/validate raw text payloads (length limits) to avoid abuse.

## 7. Known limitations to disclose in README
- No rate limiting on auth endpoints (would add in production).
- No refresh-token rotation — single long-lived JWT for prototype simplicity.
- No email verification on registration.
