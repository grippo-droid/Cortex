# Feature Ticket List — Cortex

Ordered as a build sequence. Each ticket is small enough to hand to Claude Code as a
single focused prompt/session.

## Phase 0 — Scaffolding
- [x] T0.1 Initialize backend (FastAPI project structure, requirements.txt, .env.example)
- [x] T0.2 Initialize frontend (Next.js + TS + Tailwind project structure)
- [x] T0.3 SQLAlchemy models + DB init (users, documents, chat_sessions, messages)
- [x] T0.4 docker-compose skeleton (api + db volume)

## Phase 1 — Auth (MVP)
- [x] T1.1 `POST /auth/register` with bcrypt hashing + duplicate-email handling
- [x] T1.2 `POST /auth/login` returning JWT
- [x] T1.3 `get_current_user` dependency + protect a test route
- [x] T1.4 Frontend: register + login pages, token storage, route guard

## Phase 2 — Ingestion (MVP)
- [x] T2.1 `POST /documents` — accept .txt/.md/raw text (PDF next)
- [x] T2.2 Add PDF text extraction
- [x] T2.3 Chunking function (size + overlap configurable)
- [x] T2.4 Embedding + write to per-user Chroma collection
- [x] T2.5 `GET /documents` scoped to current user
- [x] T2.6 Frontend: document dashboard (upload, list, delete)

## Phase 3 — Chat (MVP)
- [x] T3.1 `POST /chat/sessions`
- [x] T3.2 `WS /chat/stream/{session_id}` — auth + ownership check on connect
- [x] T3.3 Retrieval: embed query, similarity search user's collection
- [x] T3.4 Augmentation: system prompt + context assembly
- [x] T3.5 Generation: stream LLM tokens over the socket
- [x] T3.6 Persist user + assistant messages after completion
- [x] T3.7 Frontend: chat UI with streaming render + session sidebar

## Phase 4 — Isolation Testing (do not skip)
- [x] T4.1 Two-user manual test pass (see Security doc §3) — 18 of 18 checks
      passed. Report in `06_Isolation_Test_Report.md`; the scripts that produced
      it are in `isolation/`, so the run is reproducible rather than asserted.
- [x] T4.2 Fix any leaks found — **nothing to fix**, no leak was found. Kept
      checked rather than deleted so the pass is visible in the record.

## Phase 4.5 — System Design Hardening (light-touch, cheap wins)
- [x] T4.5.1 Add DB indexes on user_id/session_id foreign keys + cascade deletes
      — built into the models up front rather than retrofitted, and the cascade
      is verified end to end by isolation check 17.
- [x] T4.5.2 Add retry-with-backoff + timeout around embedding/LLM API calls —
      the chat path was done in T3.5; the embedding path was not, and was
      inheriting the OpenAI SDK's 600s read timeout with two silent retries.
- [x] T4.5.3 Structured logging (request id, user id, latency) on ingestion + chat routes
- [ ] T4.5.4 Basic rate limit on /auth/login and /documents (bonus if time allows)
      — **deferred**, matching the ticket's own framing. Phase 5 and 6 come
      first; revisit only if time remains.

## Phase 5 — Bonus (time-permitting, in priority order)
- [x] T5.1 Anti-hallucination system prompt + refusal behavior for out-of-scope Qs
      — the prompt was in place from T3.4; what was missing was a retrieval
      relevance threshold, so refusing an out-of-scope question is now a code
      path rather than a hope that the model obeys the prompt. The threshold was
      measured, not guessed: see `measurements/measure_distances.py`.
- [x] T5.2 Async ingestion via BackgroundTasks — validation stays synchronous so
      a bad upload still fails loudly; only chunk/embed/vector-write moved. Adds
      an `error` column so a background failure is debuggable rather than a bare
      FAILED badge, and polling on the dashboard so the status actually settles.
- [ ] T5.3 docker-compose full spin-up (app + db + chroma if server mode)
- [x] T5.4 Frontend: optimistic send — the optimistic append existed from T3.7;
      what was missing was the reconciliation half, so a question that was never
      delivered looked identical to one that was. Now pending until the server
      acknowledges it, failed with a retry control when the socket gives up.
- [x] T5.5 Frontend: WS reconnection with backoff — **done in T3.7**. The socket
      hook's state machine is the reconnection logic, so building it without
      backoff would have meant rewriting the hook's core later.
- [ ] T5.6 Frontend: dark/light mode

## Phase 6 — Submission Prep
- [x] T6.1 Write README (setup, tech choices, env vars, run instructions, limitations)
- [ ] T6.2 Compile PROMPTS.md from prompts used throughout
- [ ] T6.3 Record 2-minute walkthrough video
- [x] T6.4 Final clean-clone test: does the app run from scratch per the README?
      — run against a fresh clone, following the README literally. It found four
      breakages, all fixed in the same commit; the corrected instructions were
      then re-run start to finish as one uninterrupted pass.
