# Prompts Log

A running log of the meaningful prompts used while building Cortex. Kept as a
submission artifact per the assessment requirements.

---

## Phase 0 — Scaffolding

### Session 1 — project setup and Phase 0 plan

**Prompt:** Read CLAUDE.md fully, then read every file in `docs/` (01_PRD,
02_Technical_Architecture, 03_Security_and_Access, 04_Frontend_Spec,
05_Feature_Ticket_List). Then: confirm git identity is `Parth Mahale` /
`parthmahale2305@gmail.com` and set it locally if missing; confirm remote
`origin` points to the Cortex repo and add it if missing; confirm understanding
of the git workflow rules (no commit/push without explicit confirmation, no AI
attribution in commit messages, one commit per ticket); and propose a Phase 0
plan covering folder structure, files, and dependencies. Do not write code or
run git commands yet.

**Outcome:** Discovered the repo was not yet initialised and the five spec files
sat in the repo root rather than `docs/`. Produced a four-ticket Phase 0 plan
(backend scaffold, frontend scaffold, SQLAlchemy models, docker-compose) with a
dependency list and per-ticket commit messages.

### Session 1 — Phase 0 build

**Prompt:** Proceed with git init, identity, and remote as planned. Move the five
doc files into `docs/` as part of Phase 0, folded into the T0.1 commit. LLM
provider: OpenAI, confirmed — API key will be in `.env` before Phase 2, so don't
block Phase 0/1 on it. Keep the `bcrypt<4.1` pin. Build Phase 0 and show diffs
and proposed commit messages before committing.

**Outcome:** Initialised the repo on `main` with local identity and remote, moved
the specs into `docs/`, and built all four Phase 0 tickets.

**Notable decisions made during the build:**
- `bcrypt` pinned to `4.0.1` because passlib 1.7.4 reads `bcrypt.__about__`,
  which bcrypt >= 4.1 removed — without the pin, hashing fails in T1.1.
- `PRAGMA foreign_keys=ON` wired as a SQLAlchemy connect listener; SQLite
  silently ignores `ON DELETE CASCADE` otherwise, making the cascades decorative.
- Indexes and cascades from Architecture section 7.2 built into the models up
  front rather than retrofitted at T4.5.1 — free now, a migration later.
- `OPENAI_API_KEY` typed as optional so Phase 0/1 boot without a key.

---

## Phase 1 — Auth

### T1.1 — `POST /auth/register`

**Prompt:** Build T1.1: `POST /auth/register` with bcrypt hashing and
duplicate-email handling. Register returns `201 + UserRead` (no token); login
and JWT issuance follow in T1.2, which will also wire a token into the register
response per PRD user story 1. Use pytest with a real test file rather than a
throwaway script, so the pattern can be reused for the graded Phase 4 isolation
tests.

**Outcome:** Added the schema, hashing helpers, an `auth_service` holding the
logic, and a thin route. 13 pytest cases covering the success path, duplicate
handling, validation, and storage.

**Notable decisions made during the build:**
- Emails are lowercased and stripped before storage and before the duplicate
  check. Without it `A@x.com` and `a@x.com` become separate tenants, which would
  silently split one person's documents across two Chroma collections.
- Duplicate registration is guarded twice: a `SELECT` pre-check for the clean
  409, and an `IntegrityError` handler behind it, because two concurrent
  requests can both pass the pre-check. The `UNIQUE` constraint is the real
  guarantee.
- Password length is validated in **bytes**, not characters. bcrypt ignores
  everything past 72 bytes, so a 40-character multibyte password would otherwise
  be accepted while only partly verified.
- Test dependencies live in `requirements-dev.txt` so the Docker image does not
  ship pytest.
- `tests/conftest.py` sets `DATABASE_URL` before importing `app.config`, since
  Settings is instantiated and cached at import time. This keeps the suite off
  the developer's real `cortex.db`.

### T1.2 — `POST /auth/login` and JWT issuance

**Prompt:** Build T1.2. Both register and login return the same `AuthResponse`
(token plus user) so the client needs one round trip; update the T1.1 tests and
add `AuthResponse` to `frontend/src/types/index.ts` in the same commit. Add the
`JWT_SECRET` placeholder check now rather than deferring it to Phase 4.5 —
refuse to start if the secret is still the default, since it is a real auth
bypass risk if missed.

**Outcome:** Added `create_access_token`, `authenticate_user`, `POST
/auth/login`, and a startup guard on `JWT_SECRET`. 29 tests pass.

**Notable decisions made during the build:**
- Unknown email and wrong password return a byte-identical 401. A test asserts
  the two responses are equal, because any divergence turns login into a
  user-enumeration oracle.
- The "no such user" path still runs one bcrypt verification against a dummy
  hash. Without it the endpoint leaks the same information through response
  timing — roughly 1ms versus a few hundred.
- `sub` is stored as a string, per the JWT spec; T1.3 casts it back to `int`.
- The `JWT_SECRET` guard refuses startup on the placeholder or on any secret
  under 32 characters. A known signing key means anyone can forge a token for
  any `user_id`, and since every isolation check downstream trusts that decoded
  id, it would be a full cross-tenant read of every user's data.
- `UserLogin` sets no minimum password length: the policy belongs at
  registration, and enforcing it at login would confirm which passwords are too
  short to be real. It does keep the 72-byte ceiling, so an over-long password
  is a clean 422 rather than a 500 from bcrypt.

### T1.3 — `get_current_user` dependency

**Prompt:** Build T1.3, the `get_current_user` dependency plus a protected
route. Use `HTTPBearer(auto_error=False)` and return a uniform 401 for both
missing and invalid credentials, rather than FastAPI's default 403-then-401
split, matching the single-generic-failure pattern used for login.

**Outcome:** Added `decode_access_token`, the dependency, and `GET /auth/me` as
the protected route. 47 tests pass, 18 of them new.

**Notable decisions made during the build:**
- `decode_access_token` passes `algorithms=[settings.jwt_algorithm]` as a strict
  allow-list rather than honouring the token header's own `alg`. Verified
  directly: an `alg: none` token and an HS512-signed token are both rejected
  with "The specified alg value is not allowed", and a wrong-secret token with
  "Signature verification failed". Trusting the header is a total auth bypass
  that reads as ordinary code.
- A valid signature whose `sub` names a deleted account is rejected. The row is
  gone along with its documents and chats, so the token must stop working at
  once rather than resolving to nothing further down.
- Every rejection returns the same body, asserted by a test across three
  different causes. Divergent messages would let a caller tell a forged token
  from an expired one.
- The dependency returns the `User` object rather than a bare id, so routes
  needing the email do not pay for a second query. It is still one SELECT.
- `GET /auth/me` was chosen over a throwaway protected route: same effort, and
  the frontend needs it in T1.4 anyway.

### T1.4 — Frontend register and login

**Prompt:** Build T1.4: register and login pages, token storage, and a route
guard. Store the token in `localStorage` and document that in the README as a
known limitation. Run the browser pass directly — register, refresh, logout,
login, wrong password, duplicate email, guard redirect — and show the results.
No Vitest setup for this ticket.

**Outcome:** Added the auth context, a shared `AuthForm`, a `RequireAuth` guard,
and automatic token injection in the API client. All nine browser scenarios pass
against the running stack.

**Notable decisions made during the build:**
- `localStorage` over an httpOnly cookie: the cookie route needs CSRF handling,
  `SameSite` work across the two dev origins, and a cookie-aware WebSocket
  handshake for Phase 3. The README records the exposure and, importantly, the
  blast radius: a stolen token impersonates one user but cannot widen access,
  since scoping happens server-side from the decoded `user_id`.
- The provider holds an `isLoading` flag and the guard renders nothing while it
  is true. Without it every refresh briefly flashes the login redirect while
  `/auth/me` is still in flight.
- Login and register opt out of the global 401 handler. A rejected sign-in is a
  form error, not an expired session, and letting it trigger the session
  teardown would clear state and redirect mid-submit.
- Next 16's React Compiler lint rules rejected the first implementation twice:
  writing a ref during render, and calling `setState` synchronously inside an
  effect. Replaced the ref with a token-dependent effect registration, and moved
  the restore logic into an async function.
- The first browser run reported a false failure: `[role="alert"]` also matches
  Next's injected route announcer, which reads out the page heading. Scoping the
  selector to `form p[role="alert"]` fixed the harness; the app was correct.

---

## Phase 2 — Ingestion

### T2.1-T2.5 — the backend ingestion pipeline (batched)

**Prompt:** Move faster from here without cutting rigour: stop asking about
implementation-level decisions unless they are genuine security or isolation
trade-offs, batch tickets that group naturally, and show one summary per batch.
Build T2.1 through T2.5 — upload, PDF extraction, chunking, embedding into a
per-user vector collection, and the scoped listing endpoints.

**Outcome:** Built the full backend ingestion path. 106 tests pass, up from 47.

**Notable decisions made during the build:**
- One endpoint accepts either a file or raw text as multipart form fields, with
  exactly one required. Two endpoints would have duplicated the size, type, and
  ownership checks.
- The upload is read in 64KB blocks and aborts the moment the running total
  passes the limit. Reading it all and then checking the length would already
  have buffered a multi-gigabyte upload into memory.
- The file type allow-list keys off the filename suffix, not the declared
  content type, which a client can set to anything. A test uploads `payload.exe`
  labelled `text/plain` and expects a 415.
- Filenames are stripped of directory components (both separators, since a
  Windows client sends backslashes) and bounded to 255 characters. The value
  reaches the database, the vector metadata, and eventually the browser.
- Chunk size is measured in characters rather than tokens to avoid a tokeniser
  dependency; 2000 characters is roughly 500 tokens.
- `chunk_overlap >= chunk_size` raises rather than looping forever, and the
  chunk loop has an explicit forward-progress floor.
- Vector isolation is by collection per user, named `cortex_user_{id}` from the
  id on the verified token. `collection_name_for_user` rejects anything that is
  not an `int`, since a string there would let a caller address any collection.
- Deleting a document removes its vectors before its row: an orphaned row is
  recoverable, orphaned vectors that still answer queries are not.
- Reading or deleting another user's document returns a 404 identical to that
  of a document that does not exist, so ids cannot be probed.
- Embedding sits behind an `EmbeddingProvider` protocol. Tests swap in a
  deterministic hash-based fake, so the suite never calls a paid API.
- Tests initially shared one Chroma directory and leaked between each other:
  Chroma holds SQLite handles open, so deleting the directory silently fails on
  Windows, and one test read another's collection. Each test now gets its own
  directory. This mattered — a real isolation failure could have passed.

### Local embedding provider

**Prompt:** Switch to Groq for development to avoid OpenAI costs, implemented as
a new `EmbeddingProvider` driven by an environment variable so switching back is
configuration rather than code. Note in the README and architecture doc which
provider was used during development, and that switching requires re-uploading
documents because vector dimensions differ.

**Outcome:** Groq turned out to have no embeddings endpoint, so after checking
their documentation the local ONNX MiniLM model bundled with chromadb was used
instead. 113 tests pass.

**Notable decisions made during the build:**
- Groq publishes only chat, speech, and agentic models, and its
  OpenAI-compatibility page never mentions `/embeddings`. A
  `GroqEmbeddingProvider` was therefore impossible; Groq remains the intended
  chat provider for Phase 3.
- `all-MiniLM-L6-v2` runs through the ONNX runtime chromadb already depends on,
  so the local provider added no new dependency. Weights are about 80MB,
  downloaded once and cached, offline thereafter.
- `EMBEDDING_PROVIDER` defaults to `openai` in `.env.example`, matching the
  option the assignment names, while the local `.env` uses `local`.
- Chroma's `InvalidDimensionException` is caught and rewritten into a message
  naming the active provider and instructing a re-upload. Without it, switching
  provider produces an opaque dimensionality error at insert time.
- A chromadb build issue logs a telemetry error on every operation: it calls
  posthog's `capture()` with an outdated signature. The send always fails, so no
  data leaves the machine, but it drowns real output; that one logger is
  silenced.

### T2.6 — Frontend document dashboard

**Prompt:** Build T2.6 with native drag-and-drop, optimistic delete with
rollback, and sequential multi-file uploads. Summary and test results are
enough, since no new `user_id` scoping is introduced.

**Outcome:** Built the dashboard and, in the process, found and fixed a real
authentication bug. 11 of 11 browser scenarios pass, backend still at 113.

**Notable decisions made during the build:**
- **Bug found by the browser pass:** refreshing `/documents` signed the user
  out. React runs child effects before parent effects, so the page mounted in
  the same commit that set `user` fired its fetch before `AuthProvider`
  re-registered the token getter. The request went out unauthenticated, and the
  401 handler cleared the session. The API client now reads the token through a
  ref written wherever the token changes, so there is no ordering dependency.
  T1.4 missed this because those pages made no API calls.
- `apiFetch` passes `FormData` through without serialising it and, critically,
  without setting `Content-Type`. Only the browser knows the multipart boundary
  it generated, so setting that header by hand produces an unparseable body.
- Status badges cover all four backend states even though synchronous ingestion
  only ever returns `ready` or `failed`. When T5.2 moves ingestion to a
  background task, `pending` and `processing` start appearing with no frontend
  change.
- Multi-file uploads run sequentially so a failure names its own file rather
  than being lost among concurrent errors.
- Two harness bugs cost time and are worth remembering: `networkidle` fires
  before React hydrates, so assertions on it read an empty shell, and
  `textContent` on the body includes inline `<script>` bodies where `innerText`
  does not.

