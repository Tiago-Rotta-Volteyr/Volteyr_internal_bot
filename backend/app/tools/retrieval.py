"""
RAG tool: search the internal knowledge base (processes, FAQ) via PGVector.
"""
import os

from langchain_core.tools import tool
from langchain_openai import OpenAIEmbeddings
from langchain_postgres import PGVector

from dotenv import load_dotenv
load_dotenv()

COLLECTION_NAME = "volteyr_docs"
K = 3


def _sync_connection_string() -> str:
    """Build sync Postgres URL for PGVector (psycopg)."""
    url = os.getenv(
        "CHECKPOINT_DATABASE_URL",
        os.getenv("DATABASE_URL", "postgresql://localhost:5432/volteyr"),
    )
    if url.startswith("postgresql+asyncpg://"):
        url = "postgresql+psycopg://" + url[len("postgresql+asyncpg://") :]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


def _get_vector_store() -> PGVector | None:
    """Lazy singleton PGVector store for collection volteyr_docs."""
    if not os.getenv("OPENAI_API_KEY"):
        return None
    try:
        conn_str = _sync_connection_string()
        embeddings = OpenAIEmbeddings()
        return PGVector(
            embeddings=embeddings,
            collection_name=COLLECTION_NAME,
            connection=conn_str,
            use_jsonb=True,
        )
    except Exception:
        return None


@tool
def lookup_policy(query: str) -> str:
    """
    Search the internal knowledge base (processes, FAQ, company rules).
    Use this when the user asks about internal processes, policies, or how the company works.
    """
    store = _get_vector_store()
    if store is None:
        return "Error: Knowledge base not available (check OPENAI_API_KEY and database configuration)."
    try:
        docs = store.similarity_search(query, k=K)
        if not docs:
            return "Aucun document pertinent trouvé dans la base de connaissances."
        return "\n\n---\n\n".join(doc.page_content for doc in docs)
    except Exception as e:
        return f"Error searching knowledge base: {e}"
