# Frontend Spec — Cortex

## 1. Stack
Next.js (TypeScript, App Router) + Tailwind CSS. Component library optional
(Shadcn UI acceptable if it speeds things up).

## 2. Routes
- `/login` — email + password form, link to register.
- `/register` — email + password (+ confirm) form, client-side validation.
- `/documents` — protected; dashboard (default landing page after login).
- `/chat` — protected; chat interface, optionally `/chat/[sessionId]`.

## 3. Auth Views
- Client-side validation: email format, password min length.
- On success: store JWT (see Security doc for storage approach), redirect to `/documents`.
- Route guard: any protected route redirects to `/login` if no valid token; a 401 from
  any API call also redirects to `/login`.

## 4. Document Dashboard (`/documents`)
- Drag-and-drop zone + a manual "browse" fallback; accepts .txt, .md, .pdf.
- Upload shows a progress/processing state (pending → processing → ready), since
  ingestion may be async.
- Document list/grid: filename, upload date, chunk/status, delete action.
- Empty state with a clear call-to-action when the user has no documents yet.

## 5. Chat Interface (`/chat`)
- Sidebar: list of the user's chat sessions (most recent first), "new chat" button,
  ability to switch sessions.
- Main panel: message history (user right-aligned, assistant left-aligned or similar),
  input box pinned to bottom.
- Streaming: tokens appended to the in-progress assistant message as they arrive over
  the WebSocket; use a stable key/ref so re-renders don't cause layout shift.
- Auto-scroll to bottom on new tokens, but stop auto-scrolling if the user has manually
  scrolled up (don't yank their view).
- Optimistic send: user's message renders immediately on submit, before server ack.
- Loading/typing indicator while waiting for the first token.
- Empty/no-document state: nudge user to upload a document before chatting.

## 6. WebSocket Handling
- Connect on entering a session; include JWT in the connection handshake.
- Reconnect with exponential backoff on unexpected close; resume showing the session's
  message history (re-fetched via REST) so context isn't lost visually.
- Clear error state if reconnection ultimately fails.

## 7. Theming (bonus)
- Dark/light toggle, persisted (e.g., in a cookie or local storage), applied via
  Tailwind's `dark:` variant or a CSS variable approach.

## 8. Non-functional
- Basic responsive layout (usable on a laptop-width screen at minimum; mobile not
  required unless time allows).
- No layout shift/jank during rapid token streaming — test with a long response.
