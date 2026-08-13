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
