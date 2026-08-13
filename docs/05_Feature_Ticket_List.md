# Feature Ticket List — Cortex

Ordered as a build sequence. Each ticket is small enough to hand to Claude Code as a
single focused prompt/session.

## Phase 0 — Scaffolding
- [ ] T0.1 Initialize backend (FastAPI project structure, requirements.txt, .env.example)
- [ ] T0.2 Initialize frontend (Next.js + TS + Tailwind project structure)
- [ ] T0.3 SQLAlchemy models + DB init (users, documents, chat_sessions, messages)
- [ ] T0.4 docker-compose skeleton (api + db volume)

## Phase 1 — Auth (MVP)
- [ ] T1.1 `POST /auth/register` with bcrypt hashing + duplicate-email handling
- [ ] T1.2 `POST /auth/login` returning JWT
- [ ] T1.3 `get_current_user` dependency + protect a test route
- [ ] T1.4 Frontend: register + login pages, token storage, route guard

## Phase 2 — Ingestion (MVP)
- [ ] T2.1 `POST /documents` — accept .txt/.md/raw text (PDF next)
- [ ] T2.2 Add PDF text extraction
- [ ] T2.3 Chunking function (size + overlap configurable)
- [ ] T2.4 Embedding + write to per-user Chroma collection
- [ ] T2.5 `GET /documents` scoped to current user
- [ ] T2.6 Frontend: document dashboard (upload, list, delete)

## Phase 3 — Chat (MVP)
- [ ] T3.1 `POST /chat/sessions`
- [ ] T3.2 `WS /chat/stream/{session_id}` — auth + ownership check on connect
- [ ] T3.3 Retrieval: embed query, similarity search user's collection
- [ ] T3.4 Augmentation: system prompt + context assembly
- [ ] T3.5 Generation: stream LLM tokens over the socket
- [ ] T3.6 Persist user + assistant messages after completion
- [ ] T3.7 Frontend: chat UI with streaming render + session sidebar

## Phase 4 — Isolation Testing (do not skip)
- [ ] T4.1 Two-user manual test pass (see Security doc §3)
- [ ] T4.2 Fix any leaks found

## Phase 4.5 — System Design Hardening (light-touch, cheap wins)
- [ ] T4.5.1 Add DB indexes on user_id/session_id foreign keys + cascade deletes
- [ ] T4.5.2 Add retry-with-backoff + timeout around embedding/LLM API calls
- [ ] T4.5.3 Structured logging (request id, user id, latency) on ingestion + chat routes
- [ ] T4.5.4 Basic rate limit on /auth/login and /documents (bonus if time allows)

## Phase 5 — Bonus (time-permitting, in priority order)
- [ ] T5.1 Anti-hallucination system prompt + refusal behavior for out-of-scope Qs
- [ ] T5.2 Async ingestion via BackgroundTasks
- [ ] T5.3 docker-compose full spin-up (app + db + chroma if server mode)
- [ ] T5.4 Frontend: optimistic send
- [x] T5.5 Frontend: WS reconnection with backoff — **done in T3.7**. The socket
      hook's state machine is the reconnection logic, so building it without
      backoff would have meant rewriting the hook's core later.
- [ ] T5.6 Frontend: dark/light mode

## Phase 6 — Submission Prep
- [ ] T6.1 Write README (setup, tech choices, env vars, run instructions, limitations)
- [ ] T6.2 Compile PROMPTS.md from prompts used throughout
- [ ] T6.3 Record 2-minute walkthrough video
- [ ] T6.4 Final clean-clone test: does the app run from scratch per the README?
