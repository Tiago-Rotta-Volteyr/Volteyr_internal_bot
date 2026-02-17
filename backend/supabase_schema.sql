-- =============================================================================
-- Volteyr: threads table + RLS (Supabase-compatible)
-- Run this in Supabase SQL Editor or via migration. Do not run on local Docker
-- if you use app lifecycle create_all; use this for Supabase-hosted Postgres.
-- =============================================================================

-- pgvector extension (required for RAG / langchain PGVector)
CREATE EXTENSION IF NOT EXISTS vector;

-- Table: threads (conversation sessions; user_id = auth.users.id)
CREATE TABLE IF NOT EXISTS public.threads (
    thread_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    title       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata    JSONB NOT NULL DEFAULT '{}'
);

-- Index for RLS / listing by user
CREATE INDEX IF NOT EXISTS idx_threads_user_id ON public.threads (user_id);

COMMENT ON TABLE public.threads IS 'Chat threads; user_id matches Supabase auth.users.id. RLS enforces per-user access.';

-- =============================================================================
-- Row Level Security (RLS)
-- =============================================================================
ALTER TABLE public.threads ENABLE ROW LEVEL SECURITY;

-- Users can view their own threads
CREATE POLICY "Users can view own threads"
    ON public.threads
    FOR SELECT
    USING (auth.uid() = user_id);

-- Users can insert their own threads
CREATE POLICY "Users can insert own threads"
    ON public.threads
    FOR INSERT
    WITH CHECK (auth.uid() = user_id);

-- Users can update their own threads
CREATE POLICY "Users can update own threads"
    ON public.threads
    FOR UPDATE
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

-- Optional: users can delete their own threads
CREATE POLICY "Users can delete own threads"
    ON public.threads
    FOR DELETE
    USING (auth.uid() = user_id);
