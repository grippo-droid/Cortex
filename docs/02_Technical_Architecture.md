# Technical Architecture — Cortex

## 1. Stack
- **Backend:** Python 3.10+, FastAPI, Uvicorn
- **Relational DB:** SQLite (via SQLAlchemy) — swappable for Postgres later
- **Vector Store:** ChromaDB (local, persistent client)
- **AI Provider:** OpenAI API (or Groq/Gemini/Ollama — abstracted behind an interface)
- **Auth:** JWT (python-jose), password hashing (passlib/bcrypt)
- **Realtime:** native FastAPI WebSockets
- **Async ingestion (bonus):** FastAPI `BackgroundTasks` (upgrade path: Celery + Redis)
- **Frontend:** Next.js (TypeScript) + Tailwind CSS

## 2. High-Level Flow
```
[Browser] --HTTP(S)--> [FastAPI app] --SQL--> [SQLite: users, documents, sessions, messages]
                              |
                              +--vector ops--> [ChromaDB: per-user collections]
                              |
                              +--WS--> [chat stream] --> [OpenAI API] --> tokens streamed back
```

## 3. Component Breakdown
### 3.1 Auth Service
- `POST /auth/register` — hash password (bcrypt), create user row.
- `POST /auth/login` — verify password, issue JWT (sub=user_id, exp).
- Dependency `get_current_user` — decodes JWT on every protected route, injects `user_id`.

### 3.2 Ingestion Service
- `POST /documents` — accepts file upload or raw text.
- Text extraction: `pypdf`/`pdfplumber` for PDFs, plain read for .txt/.md.
- Chunking: recursive character/token splitter (~500-800 tokens, ~50-100 overlap).
- Embedding: OpenAI `text-embedding-3-small` (or provider equivalent).
- Storage: Chroma collection **namespaced per user** (e.g., collection name = `user_{id}`,
  or a single collection with a mandatory `user_id` metadata filter on every query).
- `GET /documents` — reads document metadata from relational DB, filtered by `user_id`.

### 3.3 Chat Service
- `POST /chat/sessions` — creates a session row scoped to `user_id`.
- `WS /chat/stream/{session_id}` — on connect, verify JWT (query param or first message)
  AND verify `session.user_id == current_user.id` before accepting.
  1. Retrieve: embed the query, similarity-search the user's Chroma collection only.
  2. Augment: build system+context prompt with retrieved chunks.
  3. Generate: stream completion from LLM, forward tokens over WS as they arrive.
  4. Persist: save user message + full assistant response to relational DB on completion.

### 3.4 Frontend
- Next.js app router; JWT stored in memory + httpOnly cookie if feasible (see Security doc).
- API client wraps fetch with auth header injection and 401 → redirect-to-login handling.
- Chat view uses a WebSocket hook with reconnect/backoff logic.

## 4. Data Model (relational)
```
users(id, email UNIQUE, hashed_password, created_at)
documents(id, user_id FK, filename, uploaded_at, chunk_count, status)
chat_sessions(id, user_id FK, title, created_at)
messages(id, session_id FK, role[user|assistant], content, created_at)
```

## 5. Vector Store Design
- One Chroma collection per user (`documind_user_{user_id}`) — simplest to reason about
  for isolation, avoids relying solely on metadata filters.
- Each chunk stored with metadata: `{document_id, chunk_index, filename}`.
- Query always scoped to the caller's own collection — never accepts a collection name
  from the client.

## 6. Deployment
- `docker-compose.yml` services: `api` (FastAPI), optionally `chroma` (if run as a server
  rather than embedded), volume-mounted SQLite file or Postgres container.
- `.env` for secrets (JWT secret, OpenAI key, DB URL).

## 7. System Design Considerations
Demonstrating awareness of these — even where the prototype takes a simpler path —
strengthens the assessment and gives good material for the "trade-offs" part of the
video.

### 7.1 Statelessness & horizontal scaling
- API instances hold no in-memory session state beyond the live WebSocket connection
  itself, so the FastAPI app is horizontally scalable behind a load balancer for HTTP.
- WebSockets are stickier: scaling chat beyond one instance needs either sticky
  sessions at the LB or a pub/sub layer (Redis) so any instance can relay tokens for a
  session owned by another instance. Note this as a scaling path, not built for MVP.

### 7.2 Database design
- Index `documents.user_id`, `chat_sessions.user_id`, and `messages.session_id` —
  every isolation-critical query filters on these.
- Foreign keys with `ON DELETE CASCADE` (deleting a user/session cleans up dependents).
- Connection pooling via SQLAlchemy's engine (matters more once moved to Postgres).

### 7.3 Caching
- Not required for a prototype's data volume, but worth naming: cache embeddings for
  identical/duplicate chunks to avoid re-embedding, and consider a short-lived cache
  for repeated identical queries within a session.

### 7.4 Rate limiting & abuse prevention
- Auth endpoints and `/documents` uploads are the obvious abuse targets (brute-force
  login, storage exhaustion). A simple in-memory or Redis-backed rate limiter
  (e.g., N requests/minute/user or /IP) is a realistic bonus addition.

### 7.5 Async processing & queues
- Embedding generation is the slow, blockable step — this is exactly why the bonus
  asks for background processing. Framed as a system design concept: decouple the
  synchronous request path from slow external I/O (embedding API calls) via a task
  queue (Celery/RQ + Redis), so `/documents` returns fast and ingestion status is
  polled or pushed separately.
- This also naturally introduces idempotency: retried embedding jobs (e.g., after a
  worker crash) shouldn't duplicate chunks — worth a unique constraint or upsert.

### 7.6 Reliability for LLM calls
- External LLM/embedding API calls can time out or fail. Wrap them with retry-with-
  backoff for transient errors, and a sane timeout so a hung request doesn't hold a
  WebSocket open indefinitely.
- Stream failures mid-response: handle gracefully (send an error frame, don't silently
  drop the client).

### 7.7 Multi-tenancy patterns
- This app uses **isolation via per-tenant partitioning** (separate Chroma collection
  per user) rather than pure row-level filtering — worth naming explicitly as a design
  choice in the video, since it's a recognized pattern (silo vs. pool multi-tenancy).
  Trade-off: simpler correctness guarantees, but more collections to manage at scale
  (a "pool" model with mandatory metadata filtering scales to more tenants with less
  overhead, at the cost of a filter bug being more catastrophic).

### 7.8 Observability
- Structured logging (request id, user id, latency) on every request, especially
  ingestion and chat, makes debugging and demonstrating correctness easier — useful
  for the walkthrough video too (e.g., showing logs proving isolation).

## 8. Trade-offs & Future Improvements
- SQLite is fine for a prototype; would move to Postgres + pgvector for production scale.
- Synchronous ingestion is simpler for MVP; background task queue is the bonus upgrade.
- No caching layer for repeated queries — acceptable at prototype scale.
