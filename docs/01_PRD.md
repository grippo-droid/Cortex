# Product Requirements Document — Cortex

## 1. Overview
Cortex is a multi-tenant, AI-powered document assistant. Users register, upload their
own documents, and chat with an AI that answers questions grounded strictly in the
content of those documents (RAG). Each user's data — documents, embeddings, and chat
history — is fully isolated from every other user.

## 2. Goals
- Demonstrate a working end-to-end RAG application within a 3-day window.
- Prove strict multi-tenant data isolation.
- Provide a real-time, streaming chat experience.

## 3. Non-Goals
- Multi-user collaboration / document sharing between accounts.
- Production-grade scaling, billing, or admin tooling.
- Support for file types beyond .txt, .md, .pdf.

## 4. User Stories
1. As a new user, I can register with email + password and receive a JWT.
2. As a returning user, I can log in and access only my own data.
3. As a user, I can upload a document and see it processed into searchable chunks.
4. As a user, I can see a list of my uploaded documents with metadata.
5. As a user, I can start a chat session and ask questions about my documents.
6. As a user, I see the AI's answer stream in token-by-token.
7. As a user, I can see and resume past chat sessions.
8. As a user, I cannot access another user's documents or chats under any circumstance,
   even if I guess or manipulate IDs.

## 5. Core Features (MVP — must ship)
- Auth: register, login, JWT-protected routes.
- Document upload (raw text, .txt, .md, .pdf) → chunk → embed → store per user.
- Document list endpoint.
- Chat session creation.
- WebSocket chat: retrieval → augmentation → streamed generation → persisted history.
- Frontend: login/register, document dashboard, chat interface.

## 6. Bonus Features (stretch — time-permitting)
- Async ingestion via background task/queue.
- Anti-hallucination system prompt (refuses out-of-scope questions).
- Docker Compose for one-command spin-up.
- Optimistic UI updates, WebSocket reconnection, dark/light mode.

## 7. Success Criteria
- A second test user cannot retrieve the first user's documents/chunks/chat history via
  any endpoint, including by ID enumeration.
- Answers are grounded in retrieved chunks; the AI declines when context is insufficient.
- Chat streams visibly token-by-token in the UI.
- App runs from a clean clone following the README with no undocumented steps.

## 8. Assumptions (edit as needed while building)
- Single deployment, no email verification required for registration.
- English-language documents only for MVP.
- Reasonable file size cap (e.g., 10MB) enforced client- and server-side.
