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
