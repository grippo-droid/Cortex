# Isolation Test Report — DocuMind

Multi-tenant isolation is the constraint this project is judged on: **a user must
never be able to access or query another user's documents or chat history.** This
report records a live test of that boundary, including attacks beyond the ones
the assessment's security requirements list.

Every check below was produced by one of the two scripts in `docs/isolation/`,
run against a live server. The quoted statuses, bodies and model answers are
actual output, not illustrations. See [Reproducing](#reproducing).

## Environment

| | |
|---|---|
| Commit tested | `4f7f6737fe9850379da31b7413d4c1e26277d838` (`main`) |
| Run at | 2026-08-14T19:28:26Z |
| Backend | Python 3.11.0, FastAPI, uvicorn on `127.0.0.1:8000` |
| Test runner | Node v24.14.0, no dependencies |
| Embedding provider | `local` — all-MiniLM-L6-v2 via ONNX, 384 dimensions |
| Chat provider | `groq` — `llama-3.3-70b-versatile` |
| Transport | Real HTTP and real WebSockets; no test client, no mocks |

The application code under test is exactly commit `4f7f673`; the only files not
in that commit are the two test scripts themselves, which run entirely over the
network and change no backend behaviour.

**Clean state.** The database and vector store accumulated during development
were moved aside and the server rebuilt both from empty. This matters: user A
was issued id `1` and document id `1`, so the id-guessing checks below probe
values that genuinely belong to another user rather than colliding with leftover
records. Both documents were confirmed to have finished ingesting, with one
chunk each, before any question was asked.

## Result

**18 of 18 checks passed.** No isolation failure was found.

Checks 1–15 come from `isolation_test.mjs` and 16–18 from
`isolation_test_deleted_user.mjs`. The numbering is contiguous and each check
appears exactly once, so the totals here can be verified against the `checks`
arrays in the two result files the scripts emit.

## Setup

| Actor | Id | Document | Chat session |
|---|---|---|---|
| User A | 1 | id 1, `ready`, 1 chunk | id 1 |
| User B | 2 | id 2, `ready`, 1 chunk | id 2 |

A's document contains the sentence *"The alpha project launch code is
HELIOTROPE-9."* B's contains unrelated notes about growing tomatoes. The string
`HELIOTROPE-9` appears nowhere in B's data, so its presence in any response to B
would be an unambiguous leak.

---

## The five required isolation checks

The assessment requires five things of the isolation boundary, restated here so
this report stands on its own: two separate accounts exist; one user's document
list excludes the other's; reading another user's document by id is refused;
opening another user's chat socket is refused; and a question only the other
user's documents could answer returns nothing of theirs.

They are checks 1, 2, 3, 5 and 7 below. Checks 4, 6 and 8 are controls added
alongside them, for reasons given in each case.

### 1. Two separate accounts exist

Registered as A (id 1) and B (id 2). Distinct ids, separate credentials. **PASS**

### 2. B's document list omits A's document

```
GET /documents          (B's token)
→ 200  [{"id": 2, "filename": "pasted-text.txt", ...}]
```

B sees exactly one document, its own. A's document id 1 is absent. **PASS**

### 3. B reading A's document by id is refused

```
GET /documents/1        (B's token)
→ 404  {"detail":"Document not found."}
```

**PASS**

### 4. The refusal cannot be used to discover which ids exist

```
GET /documents/1        (B's token)  → 404 {"detail":"Document not found."}
GET /documents/999999   (B's token)  → 404 {"detail":"Document not found."}
```

Identical status and byte-identical body. A document that belongs to someone else
is indistinguishable from one that was never created, so the endpoint cannot be
walked to enumerate real ids. **PASS**

### 5. B opening A's chat socket is rejected

```
WS /chat/stream/1       (B's own valid token in the auth frame)
→ closed, code 1008, reason "Unauthorised."
```

B's token is entirely valid; the session simply is not his. **PASS**

### 6. The socket refusal is identical for a session that does not exist

```
WS /chat/stream/1       → 1008 "Unauthorised."
WS /chat/stream/999999  → 1008 "Unauthorised."
```

Same close code, same reason. **PASS**

### 7. B asking a question only A's document can answer

B asked, in his own session: *"What is the alpha project launch code?"*

> I could not find anything in your documents that answers that. Try rephrasing
> the question, or upload a document that covers it.

No trace of A's document. The refusal comes from the relevance threshold rather
than from the model: B's only document is unrelated, every retrieved chunk is
further away than the cutoff, and a question left with no context is refused
without a model call at all. **PASS**

### 8. Control: A asking the identical question does get an answer

Without this control the check above would prove nothing, since a system that
answered nothing at all would also "pass". A asked the same question:

> The alpha project launch code is HELIOTROPE-9 [1].

The retrieval and generation path works; it simply never reaches across the
tenant boundary. **PASS**

---

## Additional attacks

The requirement is that isolation holds *"even if I guess or manipulate IDs"*,
which implies more than the five checks above.

### 9. Smuggling A's user id and collection name into the question frame

B sent a question frame carrying extra fields naming A's identity directly:

```json
{"type":"message","content":"What is the alpha project launch code?",
 "user_id":1,"collection":"documind_user_1"}
```

> I could not find anything in your documents that answers that. Try rephrasing
> the question, or upload a document that covers it.

Identical to the answer B gets without the smuggled fields. The frame is parsed
by a model that ignores unknown fields, and retrieval is scoped by the user id
taken from the verified handshake token, so neither value is ever read. **PASS**

### 10. A JWT forged with a guessed signing secret

A token was minted with `sub` set to A's id and signed with the placeholder
secret published in `.env.example`:

```
GET /documents          → 401 {"detail":"Could not validate credentials."}
WS  /chat/stream/1      → 1008 "Unauthorised."
```

**PASS** — and the application additionally refuses to start at all if
`JWT_SECRET` is left at that placeholder.

### 11. An unsigned `alg: none` token claiming to be A

The classic JWT bypass: strip the signature and declare the algorithm `none`.

```
GET /documents          → 401
WS  /chat/stream/1      → 1008
```

Verification uses a fixed algorithm allow-list rather than the algorithm named in
the token's own header. **PASS**

### 12. B reading A's chat transcript

```
GET /chat/sessions/1/messages   (B's token)
→ 404  {"detail":"Chat session not found."}
```

No message content in the response body. **PASS**

### 13. B deleting A's document and chat session

Destructive attempts matter more than reads: a silent success would destroy
another user's data.

```
DELETE /documents/1         (B's token)  → 404
DELETE /chat/sessions/1     (B's token)  → 404
GET    /documents/1         (A's token)  → 200   still present
GET    /chat/sessions/1     (A's token)  → 200   still present
```

Both refused, and A's data verified intact afterwards. **PASS**

### 14. Unauthenticated access

```
GET /documents              (no token)   → 401
WS  /chat/stream/1          (no auth frame sent)
                            → closed 1008 after the five-second timeout
```

An unauthenticated socket is not left hanging. **PASS**

### 15. Control: the attacks did no collateral damage

Run last, after every attempt above:

```
GET /auth/me            (A's token)  → 200
```

A's own access is untouched. Without this, a server that had wedged itself
partway through would make the refusals above look like successes. **PASS**

---

## A token that outlives its account

Checks 16–18 use a third account, created and then removed directly from the
database — the realistic shape of an operator deleting a user while a token
issued to them is still in circulation. There is no account-deletion endpoint, so
the row is deleted with foreign keys enabled.

### 16. Control: the token works while the account exists

```
GET /auth/me            (the account's token)  → 200
```

**PASS**

### 17. Deleting the account cascades to everything it owned

```
remaining rows -> documents: 0, sessions: 0, messages: 0
```

**PASS**

### 18. The still-valid token stops working immediately

```
GET /auth/me            → 401
GET /documents          → 401
WS  /chat/stream/{id}   → rejected, code 1008
```

The token is still cryptographically valid and unexpired; it stops working
because the user is resolved from the database on every request rather than
trusted from the token alone. **PASS**

---

## Why this holds, structurally

Tests demonstrate behaviour against the attacks that were tried. These properties
are what make the behaviour hold generally:

- **The user id enters the system in exactly one place.** `get_current_user` for
  HTTP and `authenticate_websocket` for the socket both derive it from a verified
  token. No route reads an owner from a path, query string, or request body.
- **Vector collection names are derived, never accepted.** The vector store
  exposes no function taking a collection name; every entry point takes a
  `user_id` and builds `documind_user_{id}` itself. The builder rejects any value
  that is not an integer, since a string there could name an arbitrary
  collection.
- **One collection per user**, rather than a shared collection filtered by
  metadata. A forgotten filter in a pooled design exposes every tenant; here the
  worst case is addressing a collection that does not exist.
- **Ownership has a single implementation per resource.** `get_document` and
  `get_session` both put `user_id` in the `WHERE` clause beside the id, and the
  WebSocket authorises through the same `get_session` the REST routes use, rather
  than a second copy that could drift.
- **Refusals are uniform.** Not-yours and does-not-exist return identical
  responses, so no endpoint can be used as an oracle for which ids are real.

## Limits of this report

Passing these checks shows the boundary held against the attacks listed. It is
not a proof of correctness, and no test suite could be. Specifically not covered:

- Concurrency races between simultaneous requests from different users are still
  largely untested. One was found while preparing this run and fixed: two
  uploads arriving together on a store that did not exist yet could both fail to
  ingest, because the vector store client was built without a lock and the two
  constructions raced Chroma's schema creation. It was a crash rather than a
  leak, and it is covered by a test now, but its existence is the honest
  argument for treating this line as a real gap rather than a formality.
- Timing side channels beyond the login path, which is equalised deliberately.
- The 266 automated tests back this run, but they use a fake embedding provider;
  this report is the live counterpart.
- Prompt injection from a user's own uploaded document can influence that user's
  own answers. It cannot reach another tenant, because retrieval is scoped before
  the model ever sees text, but it is a real limitation and is disclosed in the
  README.

## Reproducing

Both scripts create their own users with timestamped addresses, so the run
repeats without manual cleanup. They need Node 22 or newer and no packages; the
second also uses the backend virtualenv, which it locates relative to its own
path, to run `sqlite3`.

1. Move aside any existing `backend/documind.db` and `backend/chroma_data` so ids
   start from 1, as explained under [Clean state](#environment).
2. Start the API from `backend/`:
   `uvicorn app.main:app --host 127.0.0.1 --port 8000`
3. Run both passes from the repository root:
   ```
   node docs/isolation/isolation_test.mjs                # checks 1-15
   node docs/isolation/isolation_test_deleted_user.mjs   # checks 16-18
   ```

Each script prints one `PASS`/`FAIL` line per check, exits non-zero if any check
fails, and writes its full evidence — every recorded status, body and answer — to
`isolation_results.json` and `isolation_results_deleted_user.json` respectively.

If the server is not on `127.0.0.1:8000`, set `DOCUMIND_API` and `DOCUMIND_WS`. The
second script also accepts `DOCUMIND_DB` and `DOCUMIND_PYTHON` if your layout differs.
