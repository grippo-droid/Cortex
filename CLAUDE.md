# CLAUDE.md — Project Instructions for Cortex

This file is read automatically by Claude Code at the start of every session in this
repo. Follow these rules for the entire project.

## Project Context
Building Cortex, a multi-tenant AI-powered document assistant, per the docs in
`docs/` (01_PRD.md, 02_Technical_Architecture.md, 03_Security_and_Access.md,
04_Frontend_Spec.md, 05_Feature_Ticket_List.md). Read all five before writing any code.
Build in the phase order defined in 05_Feature_Ticket_List.md, one ticket/feature at a
time.

## Project Owner & Repo
- Author: Parth Mahale (parthmahale2305@gmail.com)
- Repository: https://github.com/grippo-droid/Cortex.git
- All commits must be authored as Parth Mahale via local git config (see below) —
  never as Claude or any AI identity.

## Git Workflow Rules — follow exactly, no exceptions
0. Confirm local git identity is set correctly before the first commit of the session:
   `git config user.name` should return `Parth Mahale` and `git config user.email`
   should return `parthmahale2305@gmail.com`. If either is missing or wrong, set it
   (locally, not global, unless I say otherwise) before proceeding:
   ```
   git config user.name "Parth Mahale"
   git config user.email "parthmahale2305@gmail.com"
   ```
1. Never run `git commit` or `git push` without my explicit confirmation in that
   session. After finishing a feature/ticket, stop, summarize what changed, propose a
   commit message, and wait for me to say "commit" / "yes" / similar before running
   any git command.
2. Commit messages must be plain and professional, in conventional-commit style where
   sensible (`feat:`, `fix:`, `chore:`, `docs:`). No mention of Claude, AI, AI-assisted
   tooling, or any AI attribution anywhere in the commit message.
3. Do not add a "Co-Authored-By" trailer or "Generated with Claude Code" text to any
   commit. `includeCoAuthoredBy` is set to false in settings — respect that.
4. Author identity for commits is already configured via `git config user.name` /
   `user.email` per step 0 — do not override it.
5. One commit per completed feature/ticket (not one giant commit at the end, and not
   multiple tiny WIP commits per ticket unless I ask for that).
6. After I confirm a commit, ask whether to push now or wait, unless I've said to
   always push immediately after committing — in which case push right after.
7. Remote is `https://github.com/grippo-droid/Cortex.git`. Confirm the remote is set
   correctly (`git remote -v`) before the first push of the session; if not set, add it
   with `git remote add origin https://github.com/grippo-droid/Cortex.git`.

## Build Process
- Work through `05_Feature_Ticket_List.md` top to bottom, one ticket at a time.
- Before starting a new phase, briefly confirm with me that the previous phase is
  working as expected.
- For Phase 4 (Isolation Testing), actually run the two-user test described in
  `03_Security_and_Access.md` §3 and show me the results before marking it done.
- Keep `PROMPTS.md` in the repo root updated with a running log of meaningful prompts
  used, since this is a required submission artifact.

## Code Style / Misc
- Python: FastAPI, type hints, keep routes thin (logic in service functions).
- Frontend: TypeScript, functional components.
- No secrets committed — use `.env` (gitignored) and keep `.env.example` current.
