/**
 * T4.1 — two-user isolation test (checks 1-15).
 *
 * Runs against a live server over real HTTP and WebSockets, with the real
 * embedding model and real chat provider. Every check records the exact request
 * and the actual response so the report is evidence, not assertion.
 *
 * Failures are recorded as findings. Nothing here is fixed silently.
 *
 * Requires Node 22+ (global fetch, FormData and WebSocket). No dependencies.
 *
 *   node docs/isolation/isolation_test.mjs
 *
 * Override the target with CORTEX_API / CORTEX_WS if the server is not on
 * 127.0.0.1:8000. Checks 16-18 live in isolation_test_deleted_user.mjs.
 */

import { writeFileSync } from "node:fs";

const API = process.env.CORTEX_API ?? "http://127.0.0.1:8000";
const WS = process.env.CORTEX_WS ?? "ws://127.0.0.1:8000";
const stamp = Date.now();

const A_EMAIL = `alice.${stamp}@example.com`;
const B_EMAIL = `bob.${stamp}@example.com`;
const PASSWORD = "correct-horse-battery";

const A_SECRET = "HELIOTROPE-9";
const A_DOC = `
Project Alpha internal memo. Classified, core team only.
The alpha project launch code is ${A_SECRET}.
The flight director is Renata Alvarez and the backup site is Kiruna.
`.trim();

const B_DOC = `
Tomato growing notes.
Tomatoes need at least six hours of direct sun each day.
Water deeply twice a week rather than lightly every day.
`.trim();

const checks = [];
function check(id, title, passed, detail, evidence) {
  checks.push({ id, title, passed, detail, evidence });
  console.log(`${passed ? "PASS" : "FAIL"}  ${id}  ${title}`);
  console.log(`        ${detail}`);
}

async function api(path, { method = "GET", token, body, json = true } = {}) {
  const headers = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  if (json && body !== undefined) headers["Content-Type"] = "application/json";

  const response = await fetch(`${API}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : json ? JSON.stringify(body) : body,
  });

  const text = await response.text();
  let parsed = null;
  try { parsed = JSON.parse(text); } catch {}
  return { status: response.status, text, json: parsed };
}

async function register(email) {
  const r = await api("/auth/register", { method: "POST", body: { email, password: PASSWORD } });
  if (r.status !== 201) throw new Error(`register failed: ${r.status} ${r.text}`);
  return { id: r.json.user.id, email, token: r.json.access_token };
}

async function uploadText(user, text) {
  const form = new FormData();
  form.append("text", text);
  const response = await fetch(`${API}/documents`, {
    method: "POST",
    headers: { Authorization: `Bearer ${user.token}` },
    body: form,
  });
  return { status: response.status, json: await response.json() };
}

/** Open the chat socket, optionally send frames, and record everything seen. */
function socketProbe(sessionId, opening, follow = null, waitMs = 25000) {
  return new Promise((resolve) => {
    const socket = new WebSocket(`${WS}/chat/stream/${sessionId}`);
    const frames = [];
    let answer = "";
    let ready = false;

    const finish = (outcome, extra = {}) =>
      resolve({ outcome, frames, answer, ...extra });

    const timer = setTimeout(() => { socket.close(); finish("timeout"); }, waitMs);

    socket.addEventListener("open", () => { if (opening !== null) socket.send(opening); });

    socket.addEventListener("message", (event) => {
      const frame = JSON.parse(event.data);
      frames.push(frame.type);

      if (frame.type === "ready") {
        ready = true;
        if (follow) socket.send(follow);
        else { clearTimeout(timer); socket.close(); finish("ready"); }
      } else if (frame.type === "token") {
        answer += frame.content;
      } else if (frame.type === "done" || frame.type === "answer") {
        if (frame.type === "answer") answer = frame.content;
        clearTimeout(timer); socket.close(); finish("answered");
      }
    });

    socket.addEventListener("close", (event) => {
      clearTimeout(timer);
      finish(ready ? "closed-after-ready" : "rejected", { code: event.code, reason: event.reason });
    });
  });
}

const authFrame = (token) => JSON.stringify({ type: "auth", token });
const askFrame = (content, extra = {}) => JSON.stringify({ type: "message", content, ...extra });

// Hand-built unsigned token.
function unsignedToken(sub) {
  const seg = (o) => Buffer.from(JSON.stringify(o)).toString("base64url");
  return `${seg({ alg: "none", typ: "JWT" })}.${seg({ sub: String(sub), exp: 9999999999 })}.`;
}
// HS256 token signed with the placeholder secret published in .env.example.
async function forgedToken(sub) {
  const { createHmac } = await import("node:crypto");
  const seg = (o) => Buffer.from(JSON.stringify(o)).toString("base64url");
  const head = seg({ alg: "HS256", typ: "JWT" });
  const body = seg({ sub: String(sub), exp: 9999999999 });
  const sig = createHmac("sha256", "change-me-to-a-long-random-string")
    .update(`${head}.${body}`).digest("base64url");
  return `${head}.${body}.${sig}`;
}

console.log("=== setup ===");
const alice = await register(A_EMAIL);
const bob = await register(B_EMAIL);
console.log(`   user A: id=${alice.id} ${alice.email}`);
console.log(`   user B: id=${bob.id} ${bob.email}`);

const aliceDoc = await uploadText(alice, A_DOC);
const bobDoc = await uploadText(bob, B_DOC);
console.log(`   A document id=${aliceDoc.json.id} status=${aliceDoc.json.status} chunks=${aliceDoc.json.chunk_count}`);
console.log(`   B document id=${bobDoc.json.id} status=${bobDoc.json.status} chunks=${bobDoc.json.chunk_count}`);

const aliceSession = (await api("/chat/sessions", { method: "POST", token: alice.token, body: {} })).json;
const bobSession = (await api("/chat/sessions", { method: "POST", token: bob.token, body: {} })).json;
console.log(`   A session id=${aliceSession.id}   B session id=${bobSession.id}\n`);

console.log("=== checks ===");

// 1. Two distinct accounts.
check("1", "Two separate accounts exist with distinct ids",
  alice.id !== bob.id,
  `A id=${alice.id}, B id=${bob.id}`,
  { aliceId: alice.id, bobId: bob.id });

// 2. B's document list omits A's document.
const bList = await api("/documents", { token: bob.token });
const bSeesA = JSON.stringify(bList.json).includes(String(aliceDoc.json.id)) &&
  bList.json.some((d) => d.id === aliceDoc.json.id);
check("2", "GET /documents as B does not include A's document",
  !bSeesA && bList.json.length === 1,
  `B sees ${bList.json.length} document(s): ${JSON.stringify(bList.json.map((d) => d.id))}; A's id ${aliceDoc.json.id} absent`,
  { request: "GET /documents (B token)", status: bList.status, body: bList.json });

// 3. B reads A's document by id.
const readForeign = await api(`/documents/${aliceDoc.json.id}`, { token: bob.token });
const readMissing = await api(`/documents/999999`, { token: bob.token });
check("3", "GET /documents/{A_id} as B is refused",
  readForeign.status === 404 && !readForeign.text.includes(A_SECRET),
  `status ${readForeign.status}, body ${readForeign.text}`,
  { request: `GET /documents/${aliceDoc.json.id} (B token)`, status: readForeign.status, body: readForeign.json });

// 4. The refusal cannot be used to enumerate which ids exist.
check("4", "Refusal is indistinguishable from a document that does not exist",
  readForeign.status === readMissing.status && readForeign.text === readMissing.text,
  `foreign: ${readForeign.status} ${readForeign.text} | missing: ${readMissing.status} ${readMissing.text}`,
  { foreign: readForeign.text, missing: readMissing.text });

// 5. B opens A's chat socket.
const wsForeign = await socketProbe(aliceSession.id, authFrame(bob.token));
const wsMissing = await socketProbe(999999, authFrame(bob.token));
check("5", "WS /chat/stream/{A_session} as B is rejected",
  wsForeign.outcome === "rejected" && wsForeign.code === 1008,
  `outcome=${wsForeign.outcome} code=${wsForeign.code} reason="${wsForeign.reason}"`,
  { request: `WS /chat/stream/${aliceSession.id} with B's valid token`, code: wsForeign.code, reason: wsForeign.reason });

// 6. Same refusal for a session that does not exist.
check("6", "Socket refusal is identical for a session that does not exist",
  wsForeign.code === wsMissing.code && wsForeign.reason === wsMissing.reason,
  `foreign: ${wsForeign.code} "${wsForeign.reason}" | missing: ${wsMissing.code} "${wsMissing.reason}"`,
  { foreign: { code: wsForeign.code, reason: wsForeign.reason }, missing: { code: wsMissing.code, reason: wsMissing.reason } });

// 7. B asks a question only A's document can answer.
const bAsk = await socketProbe(bobSession.id, authFrame(bob.token), askFrame("What is the alpha project launch code?"));
check("7", "B asking a question only A's document answers gets nothing of A's",
  !bAsk.answer.includes(A_SECRET),
  `B's answer: "${bAsk.answer.replace(/\s+/g, " ").trim().slice(0, 160)}"`,
  { request: "WS question in B's own session", answer: bAsk.answer });

// 8. A asking the same question does get it — proves the test is meaningful.
const aAsk = await socketProbe(aliceSession.id, authFrame(alice.token), askFrame("What is the alpha project launch code?"));
check("8", "A asking the same question does receive it (control)",
  aAsk.answer.includes(A_SECRET),
  `A's answer: "${aAsk.answer.replace(/\s+/g, " ").trim().slice(0, 160)}"`,
  { answer: aAsk.answer });

// 9. Smuggled user_id and collection name in the question frame.
const smuggle = await socketProbe(bobSession.id, authFrame(bob.token),
  askFrame("What is the alpha project launch code?", { user_id: alice.id, collection: `cortex_user_${alice.id}` }));
check("9", "Smuggling A's user_id and collection name into the frame is ignored",
  !smuggle.answer.includes(A_SECRET),
  `frame carried user_id=${alice.id} and collection="cortex_user_${alice.id}"; answer: "${smuggle.answer.replace(/\s+/g, " ").trim().slice(0, 130)}"`,
  { answer: smuggle.answer });

// 10. Forged JWT signed with the placeholder secret.
const forged = await forgedToken(alice.id);
const forgedRest = await api("/documents", { token: forged });
const forgedWs = await socketProbe(aliceSession.id, authFrame(forged));
check("10", "JWT forged with a guessed secret is rejected on REST and WS",
  forgedRest.status === 401 && forgedWs.code === 1008,
  `REST ${forgedRest.status} ${forgedRest.text} | WS code ${forgedWs.code}`,
  { rest: forgedRest.status, ws: forgedWs.code });

// 11. alg:none token claiming to be A.
const unsigned = unsignedToken(alice.id);
const unsignedRest = await api("/documents", { token: unsigned });
const unsignedWs = await socketProbe(aliceSession.id, authFrame(unsigned));
check("11", "Unsigned alg:none token claiming to be A is rejected",
  unsignedRest.status === 401 && unsignedWs.code === 1008,
  `REST ${unsignedRest.status} | WS code ${unsignedWs.code}`,
  { rest: unsignedRest.status, ws: unsignedWs.code });

// 12. B reads A's chat transcript.
const foreignMessages = await api(`/chat/sessions/${aliceSession.id}/messages`, { token: bob.token });
check("12", "GET /chat/sessions/{A_session}/messages as B is refused",
  foreignMessages.status === 404 && !foreignMessages.text.includes(A_SECRET),
  `status ${foreignMessages.status}, body ${foreignMessages.text}`,
  { status: foreignMessages.status, body: foreignMessages.json });

// 13. Destructive: B deletes A's document and session.
const delDoc = await api(`/documents/${aliceDoc.json.id}`, { method: "DELETE", token: bob.token });
const delSession = await api(`/chat/sessions/${aliceSession.id}`, { method: "DELETE", token: bob.token });
const aliceDocStill = await api(`/documents/${aliceDoc.json.id}`, { token: alice.token });
const aliceSessionStill = await api(`/chat/sessions/${aliceSession.id}`, { token: alice.token });
check("13", "B cannot delete A's document or chat session",
  delDoc.status === 404 && delSession.status === 404 &&
  aliceDocStill.status === 200 && aliceSessionStill.status === 200,
  `DELETE document -> ${delDoc.status}, DELETE session -> ${delSession.status}; A's document still ${aliceDocStill.status}, A's session still ${aliceSessionStill.status}`,
  { deleteDocument: delDoc.status, deleteSession: delSession.status, ownerDocument: aliceDocStill.status, ownerSession: aliceSessionStill.status });

// 14. Unauthenticated access.
const anonDocs = await api("/documents");
const anonWs = await socketProbe(aliceSession.id, null, null, 8000);
check("14", "Unauthenticated requests are refused on REST and WS",
  anonDocs.status === 401 && anonWs.code === 1008,
  `GET /documents without a token -> ${anonDocs.status}; silent socket closed with ${anonWs.code} after the auth timeout`,
  { rest: anonDocs.status, ws: anonWs.code });

// 15. Liveness control: after every attack above, A's own access is untouched.
const ownerStill = await api("/auth/me", { token: alice.token });
check("15", "A's own access is unaffected by everything attempted above (control)",
  ownerStill.status === 200,
  `GET /auth/me with A's token after all attacks -> ${ownerStill.status}`,
  { status: ownerStill.status });

console.log("\n=== summary ===");
const failed = checks.filter((c) => !c.passed);
console.log(`${checks.length - failed.length}/${checks.length} checks passed`);
if (failed.length) console.log("FAILURES: " + failed.map((f) => f.id).join(", "));

writeFileSync(
  "isolation_results.json",
  JSON.stringify({
    ranAt: new Date().toISOString(),
    users: { a: { id: alice.id, email: alice.email }, b: { id: bob.id, email: bob.email } },
    aliceDocumentId: aliceDoc.json.id,
    bobDocumentId: bobDoc.json.id,
    aliceSessionId: aliceSession.id,
    bobSessionId: bobSession.id,
    aliceAnswer: aAsk.answer,
    bobAnswer: bAsk.answer,
    smuggleAnswer: smuggle.answer,
    checks,
  }, null, 2),
);
console.log("\nwrote isolation_results.json");
if (failed.length) process.exitCode = 1;
