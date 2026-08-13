# Cortex

A multi-tenant, AI-powered document assistant. Users upload their own documents
and chat with an AI that answers strictly from those documents (RAG), with each
user's documents, embeddings, and chat history fully isolated from every other
user's.

> **Status:** Phase 0 (scaffolding). Full setup and run instructions land in T6.1.

## Stack

| Layer | Choice |
|---|---|
| Backend | Python 3.11, FastAPI, Uvicorn |
| Relational DB | SQLite via SQLAlchemy |
| Vector store | ChromaDB (embedded, persistent) |
| AI provider | OpenAI (`text-embedding-3-small`, `gpt-4o-mini`) |
| Auth | JWT (python-jose) + bcrypt (passlib) |
| Realtime | Native FastAPI WebSockets |
| Frontend | Next.js (TypeScript, App Router) + Tailwind CSS |

## Layout

```
backend/     FastAPI application
frontend/    Next.js application
docs/        PRD, architecture, security, frontend spec, ticket list
```

## Quick start (development)

```bash
# Backend
cd backend
py -3.11 -m venv .venv                           # see "Python interpreter" below
.venv/Scripts/activate                           # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                             # set JWT_SECRET; OPENAI_API_KEY needed from Phase 2
uvicorn app.main:app --reload                    # http://localhost:8000/docs

# Frontend
cd frontend
npm install
cp .env.local.example .env.local
npm run dev                                      # http://localhost:3000
```

Or with Docker:

```bash
cp backend/.env.example backend/.env             # required — compose fails without it
docker compose up --build                        # API on http://localhost:8000
```

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

### Other disclosed limitations

- No rate limiting on the auth endpoints (planned as T4.5.4).
- No refresh-token rotation; a single 24-hour JWT.
- No email verification on registration.
- HTTPS is assumed to terminate in front of the app; local development is
  plain HTTP.

## Documentation

- [Product requirements](docs/01_PRD.md)
- [Technical architecture](docs/02_Technical_Architecture.md)
- [Security and access](docs/03_Security_and_Access.md)
- [Frontend spec](docs/04_Frontend_Spec.md)
- [Feature ticket list](docs/05_Feature_Ticket_List.md)
