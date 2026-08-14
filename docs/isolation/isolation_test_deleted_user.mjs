/**
 * T4.1 continued (checks 16-18) — a token that is still cryptographically valid
 * after its account has been removed.
 *
 * There is no account-deletion endpoint, so the row is removed directly, which
 * is the realistic shape of the scenario: an operator deletes a user while a
 * token issued to them is still in circulation.
 *
 * Requires Node 22+ and the backend virtualenv (used only to run sqlite3).
 *
 *   node docs/isolation/isolation_test_deleted_user.mjs
 *
 * Paths are resolved relative to this file. Override with DOCUMIND_API,
 * DOCUMIND_WS, DOCUMIND_DB or DOCUMIND_PYTHON if your layout differs.
 */

import { execFileSync } from "node:child_process";
import { existsSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const API = process.env.DOCUMIND_API ?? "http://127.0.0.1:8000";
const WS = process.env.DOCUMIND_WS ?? "ws://127.0.0.1:8000";

// docs/isolation/<this file> -> repository root
const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "..", "..");
const BACKEND = path.join(ROOT, "backend");

const DB = process.env.DOCUMIND_DB ?? path.join(BACKEND, "documind.db");

/** The backend virtualenv if present, otherwise whatever python is on PATH. */
function resolvePython() {
  if (process.env.DOCUMIND_PYTHON) return process.env.DOCUMIND_PYTHON;
  const candidates = [
    path.join(BACKEND, ".venv", "Scripts", "python.exe"), // Windows
    path.join(BACKEND, ".venv", "bin", "python"),          // macOS / Linux
  ];
  return candidates.find(existsSync) ?? "python";
}

const PYTHON = resolvePython();

if (!existsSync(DB)) {
  console.error(`database not found at ${DB} — set DOCUMIND_DB to its location`);
  process.exit(1);
}

const email = `carol.${Date.now()}@example.com`;
const results = [];

function check(id, title, passed, detail, evidence) {
  results.push({ id, title, passed, detail, evidence });
  console.log(`${passed ? "PASS" : "FAIL"}  ${id}  ${title}\n        ${detail}`);
}

async function api(path, token) {
  const response = await fetch(`${API}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  return { status: response.status, text: await response.text() };
}

function socketProbe(sessionId, token) {
  return new Promise((resolve) => {
    const socket = new WebSocket(`${WS}/chat/stream/${sessionId}`);
    let ready = false;
    const timer = setTimeout(() => { socket.close(); resolve({ outcome: "timeout" }); }, 15000);
    socket.addEventListener("open", () => socket.send(JSON.stringify({ type: "auth", token })));
    socket.addEventListener("message", (e) => {
      if (JSON.parse(e.data).type === "ready") { ready = true; clearTimeout(timer); socket.close(); resolve({ outcome: "ready" }); }
    });
    socket.addEventListener("close", (e) => { clearTimeout(timer); if (!ready) resolve({ outcome: "rejected", code: e.code, reason: e.reason }); });
  });
}

// Set up a user with a document and a session.
const registered = await (await fetch(`${API}/auth/register`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ email, password: "correct-horse-battery" }),
})).json();

const token = registered.access_token;
const userId = registered.user.id;

const form = new FormData();
form.append("text", "Carol's private note. The vault combination is ORCHID-4. ".repeat(6));
await fetch(`${API}/documents`, { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: form });

const session = await (await fetch(`${API}/chat/sessions`, {
  method: "POST",
  headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
  body: JSON.stringify({}),
})).json();

console.log(`=== setup ===\n   user id=${userId} ${email}, session id=${session.id}`);

const before = await api("/auth/me", token);
check("16", "The token works while the account exists (control)",
  before.status === 200, `GET /auth/me -> ${before.status}`, { status: before.status });

// Remove the account directly, with foreign keys enabled so cascades fire.
const script = `
import sqlite3
conn = sqlite3.connect(r"${DB}")
conn.execute("PRAGMA foreign_keys=ON")
conn.execute("DELETE FROM users WHERE id = ${userId}")
conn.commit()
print("documents:", conn.execute("SELECT COUNT(*) FROM documents WHERE user_id = ${userId}").fetchone()[0])
print("sessions:", conn.execute("SELECT COUNT(*) FROM chat_sessions WHERE user_id = ${userId}").fetchone()[0])
print("messages:", conn.execute("SELECT COUNT(*) FROM messages WHERE session_id = ${session.id}").fetchone()[0])
conn.close()
`;
const cascade = execFileSync(PYTHON, ["-c", script], { encoding: "utf8" }).trim();
console.log(`\n=== account removed ===\n   remaining rows -> ${cascade.replace(/\n/g, ", ")}`);

check("17", "Deleting the account cascades to its documents, sessions, and messages",
  /documents: 0/.test(cascade) && /sessions: 0/.test(cascade) && /messages: 0/.test(cascade),
  `remaining rows: ${cascade.replace(/\n/g, ", ")}`, { cascade });

const afterMe = await api("/auth/me", token);
const afterDocs = await api("/documents", token);
const afterWs = await socketProbe(session.id, token);

check("18", "The still-valid token stops working the moment the account is gone",
  afterMe.status === 401 && afterDocs.status === 401 && afterWs.code === 1008,
  `GET /auth/me -> ${afterMe.status}, GET /documents -> ${afterDocs.status}, WS -> ${afterWs.outcome} code ${afterWs.code}`,
  { me: afterMe.status, documents: afterDocs.status, ws: afterWs.code });

console.log(`\n=== summary ===\n${results.filter((r) => r.passed).length}/${results.length} checks passed`);
writeFileSync("isolation_results_deleted_user.json", JSON.stringify({ email, userId, sessionId: session.id, checks: results }, null, 2));
if (results.some((r) => !r.passed)) process.exitCode = 1;
