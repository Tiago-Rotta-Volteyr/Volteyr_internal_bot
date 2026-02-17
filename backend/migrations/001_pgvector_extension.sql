-- Enable pgvector for RAG (Knowledge Base).
-- Run once on your Postgres (e.g. Supabase SQL Editor or psql).
-- langchain-postgres will create its own tables; this only enables the extension.
CREATE EXTENSION IF NOT EXISTS vector;
