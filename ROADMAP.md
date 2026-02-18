# ROADMAP: Volteyr AI Agent (Chat & Skills)

This document tracks the progress of the project. Cursor must update this file after completing each step.

## PHASE 1: Infrastructure Initialization
- [x] **Project Setup**
    - [x] Initialize Git repository.
    - [x] Create folder structure (`backend/`, `frontend/`).
    - [x] Create `.env.example` and `.gitignore`.
- [ ] **Supabase Setup**
    - [ ] Create Supabase project (or mock locally).
    - [ ] Get API URL, Anon Key, and DB Connection String.
- [x] **Docker Environment**
    - [x] Create `backend/Dockerfile` (Python 3.11-slim).
    - [x] Create `docker-compose.yml` (Backend + PostgreSQL).
    - [x] Verify Docker build and container startup.
- [x] **FastAPI Skeleton**
    - [x] Install dependencies (`fastapi`, `uvicorn`, `langgraph`, `langchain-openai`, `asyncpg`, `pydantic`).
    - [x] Create `backend/app/main.py` with a basic health check endpoint (`GET /health`).
    - [x] Configure PostgreSQL connection using `asyncpg`.
- [x] **Session Mapping Table**
    - [x] Create a `threads` table in Postgres (`thread_id` Primary Key, `user_id` Foreign Key to `auth.users`, `created_at`, `title`).
    - [x] Enable RLS (Row Level Security) on `threads` so users can only access their own rows.
    - [x] Update Backend to insert into `threads` when a new conversation starts.

## PHASE 2: Core LangGraph Logic (The Brain)
- [x] **State & Persistence**
    - [x] Define `AgentState` using `TypedDict` (messages with `add_messages` reducer).
    - [x] Setup `AsyncPostgresSaver` to persist chat history in Postgres (pooler Session port 5432 ; `CHECKPOINT_DATABASE_URL`).
- [x] **The Main Agent Node**
    - [x] Create the primary `call_model` node using GPT-4o-mini.
    - [x] Implement the system prompt (Tone, Rules) in `backend/app/agent/prompts.py`.
    - [x] Build the basic `StateGraph` (Start -> Agent -> End) in `backend/app/agent/graph.py`.
- [x] **Multi-Session Support**
    - [x] Verify that passing a `thread_id` retrieves previous conversation history (Supabase checkpoints ; script `verify_checkpoints.py`).

## PHASE 3: Skills Implementation (Sub-Agents & Tools)
- [x] **Skill 1: Airtable (Data Retrieval)**
    - [x] Create `tools/airtable.py`.
    - [x] Implement "Schema Injection" (The LLM must know the table structure) — multi-table meta-schema via `get_table_schema()`.
    - [x] Implement strict Pydantic models for the tool input (`SearchAirtableInput`, `table_name` validated against `AIRTABLE_TABLE_NAMES`).
    - [x] Bind tool to Main Agent and test retrieval (Main Agent must synthesize the JSON result). Config: `AIRTABLE_TABLE_NAMES` (comma-separated); tests in `backend/test_airtable.py`.
    - [x] **Airtable Self-Correction (Sub-Graph)** : Tool never raises (returns `Error: ...` string); Airtable sub-agent in `agent/subgraphs/airtable.py` with max 3 retries on column/API errors; main graph delegates via node `delegate_to_airtable`; debug prints `[AIRTABLE] Querying/Success/Error` in tool.
- [x] **Skill 2: RAG (Knowledge Base)**
    - [x] Setup Vector Store connection (PGVector via langchain-postgres, pgvector extension).
    - [x] Create `tools/retrieval.py` (`lookup_policy` tool), `scripts/ingest_docs.py`, `knowledge_base/`, migration `001_pgvector_extension.sql`. Tests: `test_rag.py`.
- [x] **Skill 3: Email (Human-in-the-Loop)**
    - [x] Create `tools/email.py` (Mock sending for now; print + return success message).
    - [x] Implement `interrupt_before=["tools"]` in the Graph (all tool calls require validation; V2 can filter to email only).
    - [x] Test that the graph pauses and waits for user input: `test_email_flow.py` (resume with ainvoke(None, config)).

## PHASE 4: API & Security (The Pipe)
- [x] **Authentication Middleware**
    - [x] Implement a dependency in FastAPI to verify Supabase JWT tokens.
    - [x] Extract `user_id` from the token to isolate sessions per user.
- [x] **Streaming Endpoint**
    - [x] Create `POST /api/chat` endpoint in FastAPI.
    - [x] Implement `StreamingResponse` using `graph.astream_events()`.
    - [x] Ensure output format is compatible with Vercel AI SDK (Data Stream Protocol).
- [x] **Thread security & HITL resume**
    - [x] Verify thread ownership in DB before using/resuming a thread (403 if not owner).
    - [x] Create new thread in `threads` when starting a new conversation.
    - [x] Create `POST /api/chat/resume` for human approval (approve/reject) via `Command(resume=action)`.

## PHASE 5: Frontend Development (Next.js)
- [x] **Setup**
    - [x] Initialize Next.js 14 App Router project.
    - [x] Install Shadcn UI, Tailwind, Lucide Icons.
    - [x] Install `ai` (Vercel AI SDK) and `@supabase/auth-helpers-nextjs`.
- [x] **Authentication UI**
    - [x] Create `/login` page with Supabase Auth UI (Email/Password or OAuth).
    - [x] Protect the `/` (Chat) route with middleware (redirect if not logged in).
- [x] **Chat Interface**
    - [x] Build `ChatLayout` (Sidebar + Main Area).
    - [x] Implement `useChat` hook to connect to FastAPI (passing the Auth Token).
    - [x] Render Markdown responses cleanly.
- [x] **Sidebar & History**
    - [x] Fetch list of `thread_id` belonging to the logged-in user.
    - [x] Allow switching between conversations.
- [x] **Human-in-the-Loop UI**
    - [x] Create a custom component to display when the Agent is "Paused" (Email Draft).
    - [x] Add "Approve" and "Reject" buttons that call the backend resume endpoint.

## PHASE 6: Production Polish
- [ ] **Security**
    - [ ] Audit `.env` usage (No hardcoded keys).
    - [ ] Add basic API Key protection for backend routes.
- [ ] **Deployment Config**
    - [ ] Finalize `render.yaml` (or Dockerfile) for Prod.