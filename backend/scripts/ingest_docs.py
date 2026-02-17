"""
Ingest documents from backend/knowledge_base/ into PGVector (collection "volteyr_docs").
Run from repo root: python backend/scripts/ingest_docs.py
Or from backend: python scripts/ingest_docs.py
Requires: OPENAI_API_KEY, DATABASE_URL (or CHECKPOINT_DATABASE_URL). Postgres must have pgvector extension.
"""
import os
import sys
from pathlib import Path

# Load .env from backend directory
_backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_backend_dir))
os.chdir(_backend_dir)

from dotenv import load_dotenv
load_dotenv(_backend_dir / ".env")

KNOWLEDGE_BASE_DIR = _backend_dir / "knowledge_base"
COLLECTION_NAME = "volteyr_docs"
CHUNK_SIZE = 1000


def _sync_connection_string() -> str:
    """Build sync Postgres URL for PGVector (psycopg). Prefer CHECKPOINT_DATABASE_URL."""
    url = os.getenv(
        "CHECKPOINT_DATABASE_URL",
        os.getenv("DATABASE_URL", "postgresql://localhost:5432/volteyr"),
    )
    if url.startswith("postgresql+asyncpg://"):
        url = "postgresql+psycopg://" + url[len("postgresql+asyncpg://") :]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


def main() -> None:
    if not KNOWLEDGE_BASE_DIR.is_dir():
        print(f"Creating {KNOWLEDGE_BASE_DIR}")
        KNOWLEDGE_BASE_DIR.mkdir(parents=True, exist_ok=True)

    from langchain_community.document_loaders import TextLoader, PyPDFLoader
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    from langchain_openai import OpenAIEmbeddings
    from langchain_postgres import PGVector

    loaders = []
    for path in sorted(KNOWLEDGE_BASE_DIR.iterdir()):
        if path.suffix.lower() == ".txt":
            loaders.append(("txt", TextLoader(str(path))))
        elif path.suffix.lower() == ".pdf":
            loaders.append(("pdf", PyPDFLoader(str(path))))

    if not loaders:
        print("No .txt or .pdf files in knowledge_base/. Add files and re-run.")
        return

    documents = []
    for _kind, loader in loaders:
        documents.extend(loader.load())
    print(f"Loaded {len(documents)} document(s).")

    splitter = RecursiveCharacterTextSplitter(chunk_size=CHUNK_SIZE)
    chunks = splitter.split_documents(documents)
    print(f"Split into {len(chunks)} chunk(s).")

    conn_str = _sync_connection_string()
    embeddings = OpenAIEmbeddings()
    vector_store = PGVector(
        embeddings=embeddings,
        collection_name=COLLECTION_NAME,
        connection=conn_str,
        use_jsonb=True,
    )
    vector_store.add_documents(chunks)
    print(f"Ingestion done. Collection: {COLLECTION_NAME}")


if __name__ == "__main__":
    main()
