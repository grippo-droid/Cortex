# Cortex

A multi-tenant, AI-powered document assistant. Users upload their own documents
and chat with an assistant that answers strictly from those documents (RAG),
with each user's documents, embeddings, and chat history fully isolated from
every other user's.

Isolation is the constraint the design is built around, not a feature bolted on
afterwards: see [Multi-tenant isolation](#multi-tenant-isolation), which is
backed by a live test of 18 attacks.

> A short walkthrough video is planned as a separate submission artifact; this
> README is the written setup and design reference.

## Features

- **Accounts** — register and log in; passwords hashed with bcrypt, sessions
  carried by JWT.
- **Document upload** — `.txt`, `.md`, `.pdf`, or pasted text. Files are
  extracted, chunked, embedded, and written to a vector collection belonging to
  the uploading user alone.
- **Grounded chat** — ask questions in natural language and get answers drawn
  only from your own documents, with numbered citations back to the source
  excerpt.
- **Streaming responses** — answers arrive token by token over a WebSocket,
  with automatic reconnection and backoff if the connection drops.
- **Refusal instead of invention** — a question your documents do not cover is
  refused rather than answered from the model's general knowledge. This is
  enforced in code, not only by prompt instructions; see
  [Refusing out-of-scope questions](#refusing-out-of-scope-questions).
- **Chat sessions** — multiple named conversations, each with its own history,
  persisted and reloadable.

## Stack

| Layer | Choice |
|---|---|
| Backend | Python 3.11, FastAPI, Uvicorn |
| Relational DB | SQLite via SQLAlchemy 2.0 |
| Vector store | ChromaDB (embedded, persistent), one collection per user |
| Embeddings | OpenAI `text-embedding-3-small` (default) or local `all-MiniLM-L6-v2` |
| Generation | OpenAI `gpt-4o-mini` (default) or Groq `llama-3.3-70b-versatile` |
| Auth | JWT (python-jose) + bcrypt (passlib) |
| Realtime | Native FastAPI WebSockets |
| Frontend | Next.js 16 (TypeScript, App Router) + Tailwind CSS |

Both AI providers sit behind small interfaces, so switching is a configuration
change rather than a code change. See [Providers](#providers).

## Layout

```
backend/            FastAPI application
frontend/           Next.js application
docs/               PRD, architecture, security, frontend spec, ticket list
docs/isolation/     Scripts that produce the isolation test report
docs/measurements/  Script that sets the retrieval relevance threshold
```

## Quick start

Requires Python 3.11, Node 20 or newer, and an OpenAI API key. To run without
any API key at all, see [Running without an OpenAI key](#running-without-an-openai-key).

### Backend

Create the virtual environment (see [Python interpreter](#python-interpreter) for
why `py -3.11` rather than `python`):

```bash
cd backend
py -3.11 -m venv .venv
```

Activate it. **The command differs per shell, and getting it wrong fails
silently** — running `activate` without `source` in bash exits 0, leaves the
environment untouched, and the next `pip install` goes to your global Python:

| Shell | Command |
|---|---|
| Git Bash / WSL (Windows) | `source .venv/Scripts/activate` |
| macOS / Linux | `source .venv/bin/activate` |
| PowerShell | `.\.venv\Scripts\Activate.ps1` |
| cmd.exe | `.venv\Scripts\activate.bat` |

Check it worked before continuing — `python -c "import sys; print(sys.prefix)"`
should print a path inside `.venv`.

```bash
pip install -r requirements.txt
cp .env.example .env
```

Now put a real signing secret in `.env`. **The API refuses to start while
`JWT_SECRET` is the placeholder**, which is deliberate: a known signing secret
lets anyone forge a token for any user, defeating every isolation guarantee
below.

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Paste that into `JWT_SECRET=` in `backend/.env`, add your `OPENAI_API_KEY`, then:

```bash
uvicorn app.main:app --reload          # http://localhost:8000/docs
```

### Frontend

```bash
cd frontend
npm install
cp .env.local.example .env.local       # defaults to http://localhost:8000
npm run dev                            # http://localhost:3000
```

Register an account, upload a document, and ask it something.

### Docker

Compose reads `backend/.env`, so create it and give it a real signing secret
first. Copying the example alone is not enough — it ships the placeholder
`JWT_SECRET`, and the API deliberately refuses to start on it, so the container
would restart in a loop:

```bash
cp backend/.env.example backend/.env
python -c "import secrets; print(secrets.token_urlsafe(48))"
# paste the output into JWT_SECRET= in backend/.env, and add your API key

docker compose up --build              # API on http://localhost:8000
```

That brings up the whole application — API on
[localhost:8000](http://localhost:8000) and the web interface on
[localhost:3000](http://localhost:3000). Nothing else needs installing: no
Python, no Node, no virtualenv. The first build takes several minutes, mostly
installing ChromaDB and compiling the frontend; later builds reuse the cached
layers.

The frontend waits for the API's healthcheck before starting, so `up` does not
briefly serve a page whose API is not listening yet.

**State lives in named volumes**, so `docker compose down` and `up` again keeps
your account, documents and chats. `docker compose down -v` deletes them, which
is the clean slate to use before running the isolation scripts.

A second volume caches the local embedding model. With
`EMBEDDING_PROVIDER=local` the first upload downloads about 170MB of ONNX model,
and without that volume every recreated container would download it again.

**The API URL is compiled into the frontend at build time.** `NEXT_PUBLIC_*`
values are inlined by Next during `npm run build`, so setting one at runtime has
no effect. Compose passes it as a build argument, defaulting to
`http://localhost:8000` — the address the *browser* uses, not the compose
service name. Serving this anywhere other than localhost means rebuilding the
web image with the right value:

```bash
docker compose build --build-arg NEXT_PUBLIC_API_URL=https://api.example.com web
```

## Configuration

All backend settings live in `backend/.env`. `backend/.env.example` is the
annotated template.

| Variable | Required | Default | Notes |
|---|---|---|---|
| `JWT_SECRET` | **yes** | — | Startup fails on the placeholder or under 32 chars |
| `OPENAI_API_KEY` | with `openai` providers | — | Embeddings and/or generation |
| `GROQ_API_KEY` | with `CHAT_PROVIDER=groq` | — | Generation only |
| `EMBEDDING_PROVIDER` | no | `openai` | `openai` or `local` |
| `CHAT_PROVIDER` | no | `openai` | `openai` or `groq` |
| `JWT_EXPIRE_MINUTES` | no | `1440` | 24 hours |
| `MAX_UPLOAD_MB` | no | `10` | Per file |
| `RETRIEVAL_MAX_DISTANCE` | no | `0.75` | Relevance cutoff; `0` disables |
| `DATABASE_URL` | no | `sqlite:///./cortex.db` | |
| `CHROMA_PERSIST_DIR` | no | `./chroma_data` | |
| `CORS_ORIGINS` | no | `http://localhost:3000` | Comma-separated |

Timeout and retry bounds for both providers are configurable and documented in
`.env.example`; the defaults are sensible and rarely need changing.

The frontend reads one variable, `NEXT_PUBLIC_API_URL`. Nothing secret belongs
in it — `NEXT_PUBLIC_*` values are compiled into the browser bundle.

## API

All routes except registration and login require `Authorization: Bearer <token>`.
Interactive documentation is at `/docs` when the server is running.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/auth/register` | Create an account, returns a token and the user |
| `POST` | `/auth/login` | Exchange credentials for a token |
| `GET` | `/auth/me` | The current user |
| `POST` | `/documents` | Upload a file or pasted text |
| `GET` | `/documents` | List **your** documents |
| `GET` | `/documents/{id}` | One document, if you own it |
| `DELETE` | `/documents/{id}` | Delete a document and its vectors |
| `POST` | `/chat/sessions` | Start a chat session |
| `GET` | `/chat/sessions` | List **your** sessions |
| `GET` | `/chat/sessions/{id}` | One session, if you own it |
| `GET` | `/chat/sessions/{id}/messages` | Transcript, if you own it |
| `DELETE` | `/chat/sessions/{id}` | Delete a session and its messages |
| `WS` | `/chat/stream/{id}` | Ask questions and stream answers |

Requesting something owned by another user returns exactly what requesting
something nonexistent returns — see [Multi-tenant isolation](#multi-tenant-isolation).

### WebSocket protocol

A browser cannot set headers on a WebSocket handshake, so the token travels in
the first message rather than in a query parameter. Query strings end up in
server logs, proxy logs, and browser history, and a token leaked there is a live
session until it expires.

The client sends:

```jsonc
{"type": "auth", "token": "<jwt>"}                 // must be first
{"type": "message", "content": "your question"}
```

The server replies with `ready` once authenticated and the session's ownership
is confirmed, then per question: `sources` (the excerpts retrieved), `start`,
a stream of `token` frames, and `done`. A question needing no model call
returns a single `answer` frame instead. Failures arrive as `error`.

Authentication or ownership failure closes the socket with code `1008` and the
reason `Unauthorised.` — identical for a session that does not exist.

## Multi-tenant isolation

**No user can read, query, or delete another user's documents or chat history.**

The design choices that make this hold:

- **The user id enters the system in exactly one place.** `get_current_user`
  for HTTP and `authenticate_websocket` for the socket both derive it from a
  verified token. No route reads an owner from a path, query string, or body.
- **One vector collection per user**, named `cortex_user_{id}`, rather than a
  shared collection filtered by metadata. A forgotten filter in a pooled design
  exposes every tenant; here the worst case is addressing a collection that does
  not exist. The name is always derived from the verified id and never accepted
  as input.
- **Ownership has a single implementation per resource.** `user_id` sits in the
  `WHERE` clause beside the row id, and the WebSocket authorises through the
  same function the REST routes use rather than a second copy that could drift.
- **Refusals are uniform.** "Not yours" and "does not exist" return identical
  status codes and identical bodies, so no endpoint can be used to discover
  which ids are real.
- **The token is not trusted on its own.** The user is loaded from the database
  on every request, so a token outliving its account stops working immediately.

### Verifying it

[`docs/06_Isolation_Test_Report.md`](docs/06_Isolation_Test_Report.md) records a
live run against a real server: **18 of 18 checks passed.** It covers the five
checks the security document requires plus thirteen more, including id guessing,
smuggling another user's id and collection name into the chat frame, a JWT
forged with the published placeholder secret, an unsigned `alg:none` token,
cross-user deletes, and a token that outlives its account.

The report is reproducible rather than asserted — the scripts that produced it
are committed:

```bash
# with the API running on 127.0.0.1:8000
node docs/isolation/isolation_test.mjs                # checks 1-15
node docs/isolation/isolation_test_deleted_user.mjs   # checks 16-18
```

They need Node 22 or newer, for the global `WebSocket`, and no packages. Each
prints one line per check, exits non-zero if any fails, and writes its full
evidence to a JSON file. Start from an empty `cortex.db` and `chroma_data` so
the two users are issued low ids and the id-guessing checks probe values that
genuinely belong to someone else.

## How it works

**Ingestion.** An upload is validated and extracted (PDF via pypdf, text as-is)
while the request is still open, then recorded as `pending` and returned. The
rest — splitting into overlapping character-based chunks, embedding them in one
batch, and writing them to the uploader's own Chroma collection with filename
and chunk index attached — runs in the background, moving the document through
`processing` to `ready` or `failed`. The dashboard polls until it settles.

**Retrieval.** A question is embedded and compared against that user's
collection only. Hits further away than `RETRIEVAL_MAX_DISTANCE` are dropped as
unrelated.

**Augmentation.** Surviving chunks are numbered, fenced, and labelled with their
source, then placed immediately before the question. Recent conversation turns
are included within a character budget; the system prompt and the current
question are never dropped by trimming.

**Generation.** The prompt is streamed to the chat model and tokens are relayed
to the browser as they arrive. Both messages are persisted after completion.

### Refusing out-of-scope questions

The system prompt instructs the model to answer only from the supplied context
and to refuse otherwise. That alone is a hope, not a guarantee — it depends on
the model choosing to comply, and compliance is exactly what degrades under
pressure or with a weaker model.

So refusal is also a code path. Retrieved chunks further than a cosine distance
threshold are discarded, and a question with nothing left is refused without
calling the model at all.

The threshold was measured rather than guessed, using three question classes
against a known corpus:

| Question class | Best-hit cosine distance (min / median / max) |
|---|---|
| Answerable from the corpus | 0.16 / 0.26 / **0.46** |
| Related, but not answered | **0.46** / 0.57 / 0.64 |
| Unrelated | **0.80** / 0.93 / 0.97 |

The default of `0.75` sits in the gap, deliberately nearer the unrelated end: a
false refusal is worse than an occasional over-answer. Note that answerable and
related-but-unanswered are *not* separable by distance — the second band begins
0.004 above the first band's worst case. That is intentional. Those questions
should reach the model, which can explain what the documents do and do not
cover, rather than receive a blunt canned reply.

Re-run the measurement after changing embedding provider, since the distance
scale is model-specific:

```bash
cd backend
EMBEDDING_PROVIDER=local PYTHONPATH=. python ../docs/measurements/measure_distances.py
```

### Prompt injection

Retrieved text is fenced and labelled as data, and the system prompt instructs
the model to describe rather than obey any instructions found inside it. This is
a mitigation, not a guarantee. Its limits are covered under
[Known limitations](#known-limitations).

## Providers

The application is provider-agnostic: everything downstream depends on small
interfaces, so changing provider is a configuration change.

| `EMBEDDING_PROVIDER` | Model | Dimensions | Cost | Key |
|---|---|---|---|---|
| `openai` *(default)* | `text-embedding-3-small` | 1536 | paid | `OPENAI_API_KEY` |
| `local` | `all-MiniLM-L6-v2` (ONNX) | 384 | free | none |

| `CHAT_PROVIDER` | Model | Cost | Key |
|---|---|---|---|
| `openai` *(default)* | `gpt-4o-mini` | paid | `OPENAI_API_KEY` |
| `groq` | `llama-3.3-70b-versatile` | free tier | `GROQ_API_KEY` |

`openai` is the configured default for both, matching the primary option named
in the assignment.

**Development and testing were carried out against `local` embeddings and
`groq` generation, for cost reasons.** The local model runs entirely on the
machine through the ONNX runtime ChromaDB already depends on, so no volume of
testing incurs any charge; its weights (about 80MB) download once on first use
and every run afterwards is offline. Groq's API is OpenAI-compatible, so both
chat providers share one client with a different base URL and model.

Groq is not offered as an *embedding* provider: it serves chat completions only
and has no embeddings endpoint.

### Running without an OpenAI key

```bash
EMBEDDING_PROVIDER=local
CHAT_PROVIDER=groq
GROQ_API_KEY=gsk_...
```

Embeddings then cost nothing and run offline, and generation uses Groq's free
tier. This is the configuration the project was built against.

### Switching embedding provider requires re-uploading documents

**Embeddings from different providers are not interchangeable.** They have
different dimensions — 1536 against 384 here — and even at matching dimensions
the vector spaces are unrelated, so a similarity score between them is
meaningless. ChromaDB rejects the mismatch rather than silently returning
nonsense, and the application turns that into an explicit error naming the
current provider and telling you to re-upload.

After changing `EMBEDDING_PROVIDER`, delete and re-upload every document.
Deleting a document removes its vectors; re-uploading re-embeds with the newly
selected provider. Changing `CHAT_PROVIDER` costs nothing, since nothing
generated is stored.

## Testing

The test tools are a separate requirements file, so the Docker image stays slim.
Install them once into the same virtual environment:

```bash
cd backend
pip install -r requirements-dev.txt   # pytest and httpx; includes requirements.txt
pytest                                # 261 tests
pytest -m "not slow"                  # skips the tests that load the real ONNX model
```

The suite uses fake embedding and chat providers, so it never calls a paid API
and never spends tokens. Each test gets its own database and its own Chroma
directory — shared directories on Windows leave the previous test's collections
readable, which could let a genuine isolation failure pass unnoticed.

Beyond unit tests:

- **Isolation** — `docs/isolation/*.mjs`, described above. Real HTTP, real
  WebSockets, real vectors, real model.
- **Relevance threshold** — `docs/measurements/measure_distances.py`, which
  reports the distance data behind `RETRIEVAL_MAX_DISTANCE`.

## Design decisions

**One vector collection per user, not a shared one with metadata filters.**
The pooled approach is more efficient and is the common default, but its
isolation depends on every query remembering to include the filter. One
forgotten `where` clause exposes every tenant at once. Per-user collections make
the failure mode "collection not found" instead of "someone else's documents".

**Token in the WebSocket's first message, not the query string.** Query strings
are recorded in access logs, proxy logs, and browser history. The socket is
accepted before the token can be read, so an unauthenticated socket exists
briefly — it is sent nothing, touches no session data, and is closed after five
seconds of silence.

**Uniform refusals.** Distinguishing "forbidden" from "not found" is more
honest to a legitimate caller, but it turns every endpoint into an oracle for
which ids exist. Both return 404 with an identical body.

**Retry only before the first token.** A failure mid-stream cannot be retried
without repeating text the user has already read, so retries stop as soon as any
output is produced. Embedding calls are atomic and so are always retryable.

**Refusal enforced in code, not only in the prompt.** Explained under
[Refusing out-of-scope questions](#refusing-out-of-scope-questions).

**Structured logging.** Every request and WebSocket connection emits one JSON
line with a request id, the authenticated user id, path, outcome, and latency,
which is what makes an operational question about one user answerable. An
inbound `X-Request-ID` is reused so a trace can span services.

## Local development notes

### Python interpreter

Create the virtualenv with a standard CPython 3.11 (`py -3.11` on Windows), not
whatever `python` happens to resolve to on `PATH`.

On at least one dev machine here `python` resolved to an MSYS2/MinGW build
(`C:\...\ucrt64\bin\python.exe`). That build lays venvs out POSIX-style — `bin/`
instead of `Scripts/`, so `.venv\Scripts\activate` does not exist — and reports a
platform tag that does not match the `win_amd64` wheels on PyPI, so pip tries to
compile ChromaDB's native dependencies (onnxruntime, tokenizers, pydantic-core)
from source and fails. Using `py -3.11` installs every dependency as a prebuilt
wheel.

### Windows: clone somewhere shallow

Tip rather than requirement: `onnxruntime`, pulled in by ChromaDB, ships some
very deeply nested file paths. Cloning into an already-deep directory can push
those past Windows' 260-character path limit, and `pip install` then fails part
way through with `OSError: [Errno 2] No such file or directory` naming a long
`onnxruntime` path.

Cloning somewhere short, such as `C:\dev\Cortex`, avoids it entirely.
Alternatively enable long-path support (`git config --system core.longpaths true`
and the `LongPathsEnabled` registry setting).

### SQLite and foreign keys

SQLite does not enforce foreign keys — including `ON DELETE CASCADE` — unless
`PRAGMA foreign_keys=ON` is issued on **each connection**. `app/database.py`
registers a SQLAlchemy `connect` event listener that does this, which is what
makes the cascade deletes in `app/models.py` real rather than decorative.

If you swap SQLite for Postgres, that listener becomes a no-op (it is guarded on
the driver) and Postgres enforces the constraints natively.

## Known limitations

### Token storage (localStorage)

The frontend stores its JWT in `localStorage` under `cortex.token`. **Any script
running on the page can read it**, so a cross-site scripting bug would leak an
active session token.

The security document prefers an httpOnly cookie set by the backend, and permits
this fallback provided it is disclosed. It is chosen deliberately here: a cookie
would require CSRF protection, `SameSite`/`Secure` handling across the
`localhost:3000` to `localhost:8000` origin split, and a cookie-aware WebSocket
handshake — none of which fits the prototype's time budget. Holding the token in
memory only would avoid the exposure but would sign the user out on every page
refresh.

Worth being precise about the blast radius: a stolen token impersonates one
user. It does not widen access, because every query is scoped server-side to the
`user_id` decoded from the token. Tenant isolation does not depend on where the
client keeps it.

For production: move to an httpOnly, `Secure`, `SameSite=Lax` cookie, add CSRF
tokens on state-changing routes, and shorten the token lifetime with refresh
rotation.

### Prompt injection within a tenant

A document you upload can influence the answers you get about your own
documents. The fencing and the "data, never instructions" rule in the system
prompt reduce this, but no prompt-level mitigation is complete.

It cannot cross the tenant boundary: retrieval is scoped to one user's
collection before the model sees any text, so an injected instruction has no
path to another user's documents.

### Relevance threshold is unmeasured on OpenAI

`RETRIEVAL_MAX_DISTANCE=0.75` was measured on `all-MiniLM-L6-v2`. Cosine
distance is normalised, so the scale transfers better than an unnormalised
metric would, but the value has **not** been verified against
`text-embedding-3-small`. Re-run `docs/measurements/measure_distances.py` after
switching, and adjust if the bands differ.

### Ingestion is background work, not a durable queue

Uploads return as soon as the document is recorded, and chunking, embedding and
the vector write happen in a FastAPI `BackgroundTasks` callback. That keeps a
large PDF from holding its request open, but the work runs **in the same
process**: it does not survive a restart, there is no retry, and no second
worker will pick it up. A process killed mid-ingestion leaves that document
stuck in `processing` with no automatic recovery, and the only way out is to
delete it and upload again.

Validation is deliberately not deferred. An unsupported file type or an
oversized upload is still refused at request time with a real status code;
only the slow half moved. Failures inside the background task are recorded on
the document and shown in the dashboard, since the upload response has already
been sent by then.

A real deployment would move this to a durable queue (Celery, RQ, or an outbox
table polled by a worker) so ingestion survives restarts and can be retried.

### Other disclosed limitations

- No rate limiting on the auth endpoints. Deferred deliberately; it is the one
  hardening item consciously left undone.
- No refresh-token rotation; a single 24-hour JWT.
- No email verification on registration.
- No database migrations. `create_all` builds missing tables, and a small
  guarded step adds columns introduced after the first release; anything beyond
  that needs Alembic.
- SQLite and embedded Chroma suit a single-process deployment; multi-process
  scaling would want Postgres and a Chroma server.
- HTTPS is assumed to terminate in front of the app; local development is plain
  HTTP.

## Documentation

- [Product requirements](docs/01_PRD.md)
- [Technical architecture](docs/02_Technical_Architecture.md)
- [Security and access](docs/03_Security_and_Access.md)
- [Frontend spec](docs/04_Frontend_Spec.md)
- [Feature ticket list](docs/05_Feature_Ticket_List.md)
- [Isolation test report](docs/06_Isolation_Test_Report.md)
