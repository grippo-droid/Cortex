# Prompts Used

**Project: DocuMind**

This document contains a representative record of prompts I used while developing **DocuMind**. It focuses on meaningful instances where I used AI to assist with implementation, debugging, technical explanations, and code-level suggestions rather than documenting every interaction.

I used AI as a development assistant for implementation-level help such as code snippets, API/framework guidance, debugging, refactoring, test ideas, and security reviews. I was responsible for understanding the assessment requirements, deciding the overall architecture and technology stack, implementing and integrating the features, and reviewing any AI-generated suggestions before using them in the project.

The prompts below are representative examples of the questions and requests I made during development. They are not a complete transcript, and they should not be interpreted as a record of the AI independently building the application.

---

## Phase 0 — Project Setup

### Project structure and architecture

**Prompt:**

> Review the project requirements and help me plan a clean folder structure for a FastAPI backend and Next.js frontend. The application needs authentication, document ingestion, vector search, RAG-based chat, WebSocket streaming, a SQLite database via SQLAlchemy, and an embedded vector store. Keep the structure modular and easy to extend.

**Used for:**

- Initial project organization
- Backend/frontend separation
- Service and router organization
- Identifying the main dependencies required for the project

---

### Database models

**Prompt:**

> Based on the requirements, suggest SQLAlchemy models for users, documents, chat sessions, and messages. Include appropriate relationships, foreign keys, timestamps, indexes, and cascade behavior. Explain any important design decisions.

**Used for:**

- Creating the initial SQLAlchemy model structure
- Reviewing relationships between users, documents, sessions, and messages
- Identifying useful database constraints and indexes

---

### Docker setup

**Prompt:**

> Help me create a Docker Compose setup for a FastAPI application and a Next.js frontend, with persistent volumes for the SQLite database and the embedded Chroma vector store. Keep the configuration suitable for local development and make the environment variables configurable through `.env`.

**Used for:**

- Initial Docker configuration
- Local development environment
- Service configuration and environment variables

---

## Phase 1 — Authentication

### User registration

**Prompt:**

> Help me implement a FastAPI registration endpoint using SQLAlchemy. The endpoint should validate the email, hash the password securely using bcrypt, handle duplicate emails cleanly, and return a safe user response without exposing the password hash.

**Used for:**

- Registration endpoint
- Password hashing
- Validation
- Duplicate email handling
- Response schema

---

### Login and JWT authentication

**Prompt:**

> Show me a clean FastAPI implementation for login using bcrypt password verification and JWT access tokens. The token should contain the user's ID and have an expiration time. Also show how to structure the authentication service separately from the API route.

**Used for:**

- Login implementation
- JWT creation
- Password verification
- Authentication service structure

---

### Protected routes

**Prompt:**

> Explain how to create a FastAPI dependency that extracts and validates a JWT from the Authorization header and returns the authenticated user. Include handling for expired, malformed, and invalid tokens.

**Used for:**

- `get_current_user`
- Protected API routes
- JWT validation
- Authentication error handling

---

### Authentication security review

**Prompt:**

> Review this authentication implementation for common security issues such as user enumeration, weak JWT validation, insecure password handling, and incorrect authorization checks. Suggest improvements without changing the overall architecture.

**Used for:**

- Security review
- Identifying authentication edge cases
- Improving error handling
- Reviewing JWT validation

---

### Frontend authentication

**Prompt:**

> Help me implement login and registration pages in Next.js with TypeScript. I need an authentication context, protected routes, API token handling, loading state during session restoration, logout, and proper form error handling.

**Used for:**

- Authentication UI
- Auth context
- Route protection
- API integration
- Session restoration

---

## Phase 2 — Document Ingestion

### Document upload

**Prompt:**

> Help me implement a FastAPI document upload endpoint that accepts PDF, TXT, and Markdown files as well as raw text. Add file type validation, filename sanitization, and a reasonable upload size limit. The implementation should avoid loading unnecessarily large files into memory.

**Used for:**

- Upload endpoint
- File validation
- Filename handling
- Upload size protection

---

### PDF text extraction

**Prompt:**

> Show me how to extract text from PDF files in Python using pypdf. Handle PDFs with multiple pages and return clean text that can be passed into a chunking pipeline.

**Used for:**

- PDF processing
- Text extraction
- Multi-page document handling

---

### Text chunking

**Prompt:**

> Explain a simple chunking strategy for RAG documents. I want chunks that are small enough for embedding and retrieval while retaining enough surrounding context. Suggest a reasonable chunk size and overlap and provide a Python implementation.

**Used for:**

- Chunking implementation
- Chunk size selection
- Overlap handling

---

### Embedding provider

**Prompt:**

> Help me design an embedding provider abstraction so that the application can switch between a local embedding model and an API-based provider through environment configuration instead of changing application code.

**Used for:**

- Embedding abstraction
- Provider interface
- Configuration-based provider selection

---

### Vector storage

**Prompt:**

> Show me how to store document embeddings in ChromaDB with metadata such as user ID, document ID, filename, and chunk index. I need the design to support strict user-level document isolation during retrieval.

**Used for:**

- Vector storage
- Metadata design
- Document/chunk association

---

### Multi-tenant vector retrieval

**Prompt:**

> Review this RAG retrieval function and check whether a user could retrieve another user's documents. The authenticated user's ID should come from the verified JWT and should never be trusted from the request body. Suggest changes if necessary.

**Used for:**

- Reviewing tenant isolation
- Preventing client-controlled user IDs
- Scoping vector retrieval

---

### Document listing and ownership

**Prompt:**

> Help me implement document listing, retrieval, and deletion so that users can only access their own documents. What is the safest way to handle requests for another user's document ID?

**Used for:**

- Document authorization
- Ownership checks
- Preventing document ID enumeration

---

## Phase 3 — RAG Chat

### Chat sessions

**Prompt:**

> Help me design REST endpoints for creating, listing, retrieving, and deleting chat sessions. Each session must belong to the authenticated user and users must not be able to access another user's sessions or messages.

**Used for:**

- Chat session API
- Session ownership
- Chat history access control

---

### WebSocket authentication

**Prompt:**

> I need to authenticate a browser WebSocket connection in FastAPI. Since the browser WebSocket API does not allow arbitrary Authorization headers, explain the safest practical approach for this application and show the server-side implementation.

**Used for:**

- WebSocket authentication design
- Authentication handshake
- Session ownership validation

---

### WebSocket connection handling

**Prompt:**

> Review this FastAPI WebSocket handler for authentication, connection timeout, invalid messages, and unauthorized session access. Suggest improvements that keep the socket stable for normal client errors.

**Used for:**

- WebSocket error handling
- Authentication failures
- Connection timeout
- Message validation

---

### Retrieval

**Prompt:**

> Help me connect the WebSocket chat flow to the vector database. When a user sends a question, generate its embedding, search only the authenticated user's document collection, and return the most relevant chunks for use as context.

**Used for:**

- RAG retrieval pipeline
- Query embeddings
- Tenant-scoped similarity search

---

### Prompt augmentation

**Prompt:**

> Help me design a system prompt for a document-grounded assistant. The model should answer only from retrieved document context, avoid making up information, and clearly state when the context does not contain an answer. Treat retrieved document text as data rather than instructions.

**Used for:**

- RAG system prompt
- Anti-hallucination behavior
- Basic prompt-injection mitigation

---

### Context and conversation history

**Prompt:**

> Suggest a way to combine retrieved document chunks, recent conversation history, and the current user question while keeping the prompt within a reasonable token budget. The current question must always be preserved.

**Used for:**

- Prompt construction
- Conversation history
- Context limits

---

## Phase 4 — LLM Streaming

### LLM provider integration

**Prompt:**

> Show me how to integrate Groq's OpenAI-compatible API into a Python application and stream the generated response. Keep the provider behind a service abstraction so the rest of the application does not depend directly on the SDK.

**Used for:**

- Groq integration
- Provider abstraction
- Streaming generation

---

### Async streaming

**Prompt:**

> The LLM SDK returns a synchronous streaming generator while my FastAPI WebSocket handler is asynchronous. Explain how to consume the stream without blocking the event loop or other connected users.

**Used for:**

- Async/sync integration
- Streaming architecture
- Concurrent WebSocket handling

---

### Streaming error handling

**Prompt:**

> Review this streaming implementation and suggest how to handle errors before the first token versus errors after partial output has already been sent. The client should not receive a fake completed response if generation fails.

**Used for:**

- Streaming error handling
- Partial response handling
- Client-side reconciliation

---

## Phase 5 — Persistence

### Chat history

**Prompt:**

> Help me persist user messages and assistant responses for each chat session. The user message should be saved before generation and the final assistant response should be saved after streaming completes. Also consider how to represent a partial response if the connection fails.

**Used for:**

- Message persistence
- Conversation history
- Partial-response handling

---

### Reconnection

**Prompt:**

> Suggest a reliable WebSocket reconnection strategy for a React chat application. When reconnecting, the client should retrieve the persisted conversation from the backend instead of assuming that its local streaming state is complete.

**Used for:**

- WebSocket reconnection
- Conversation recovery
- Client/server state synchronization

---

## Phase 6 — Frontend Chat

### Chat interface

**Prompt:**

> Help me build a clean React/Next.js chat interface with a session sidebar, message list, composer, loading state, and streaming assistant response. Keep the components modular and avoid unnecessary state complexity.

**Used for:**

- Chat UI
- Session sidebar
- Message components
- Composer

---

### Streaming UI performance

**Prompt:**

> Review this React streaming implementation. Tokens arrive very quickly, so I want to avoid triggering a React render for every individual token. Suggest a simple batching strategy that keeps the UI responsive while still appearing real-time.

**Used for:**

- Streaming rendering optimization
- Render batching
- UI performance

---

### Auto-scroll

**Prompt:**

> Show me a chat auto-scroll implementation that follows new messages while the user is already near the bottom, but does not forcibly scroll when the user is reading older messages.

**Used for:**

- Chat scrolling
- User experience improvements

---

## Phase 7 — Testing and Debugging

### Backend tests

**Prompt:**

> Suggest pytest test cases for this FastAPI endpoint, including successful requests, validation errors, authentication failures, duplicate records, and unauthorized access.

**Used for:**

- Test coverage
- Edge-case identification
- Regression tests

---

### Multi-tenant isolation tests

**Prompt:**

> Help me design integration tests for multi-tenant isolation. Create two users with separate documents and chat sessions and verify that neither user can access the other's documents, vector results, sessions, or messages.

**Used for:**

- Security testing
- Tenant isolation verification
- Authorization regression tests

---

### Debugging

**Prompt:**

> Here is the error and the relevant code. Explain the likely cause, identify the smallest safe fix, and explain why the fix works. Do not redesign unrelated parts of the application.

**Used for:**

- Debugging runtime errors
- Understanding framework behavior
- Small targeted fixes

---

### Frontend debugging

**Prompt:**

> Review this React component and explain why the state/request is behaving incorrectly after a page refresh. Identify the lifecycle or dependency issue and suggest a minimal fix.

**Used for:**

- React lifecycle debugging
- Authentication state restoration
- API request timing issues

---

## Phase 8 — Final Review

### Security review

**Prompt:**

> Perform a security review of the current application architecture. Focus specifically on authentication, authorization, JWT handling, user/document ownership, vector database isolation, WebSocket authentication, file uploads, and prompt injection. List concrete issues and improvements in priority order.

**Used for:**

- Final security review
- Identifying missing authorization checks
- Reviewing tenant isolation

---

### RAG review

**Prompt:**

> Review the complete document ingestion and RAG pipeline and identify possible failure points from upload through chunking, embedding, retrieval, prompt construction, and LLM generation. Focus on correctness and practical improvements rather than adding unnecessary complexity.

**Used for:**

- End-to-end RAG review
- Error handling
- Pipeline validation

---

### README review

**Prompt:**

> Review my README for a technical assessment submission. Check whether another developer can clone the repository, configure environment variables, start the backend/frontend/database/vector store, and understand the architecture and known limitations. Suggest missing information.

**Used for:**

- Documentation review
- Setup instructions
- Environment variable documentation

---

### AI Assistance Scope

AI tools were used as a supporting development aid rather than as an autonomous developer for the project.

Typical uses included:

- Generating small code snippets, boilerplate, and implementation examples
- Explaining framework and library APIs
- Suggesting approaches for individual implementation problems
- Helping diagnose and debug errors
- Reviewing code for security issues and edge cases
- Suggesting additional test cases
- Helping with frontend component structure and API integration
- Reviewing RAG prompts and retrieval behavior
- Assisting with refactoring and documentation

The project direction was driven by my understanding of the assessment requirements. I made the decisions about the architecture, technology choices, feature scope, security model, and how the different components should work together. AI-generated suggestions were reviewed, adapted where necessary, and integrated only when they fit the project's requirements.

This document intentionally presents selected examples of AI-assisted development work. It does not represent the project as being generated or operated entirely by an AI coding agent.
