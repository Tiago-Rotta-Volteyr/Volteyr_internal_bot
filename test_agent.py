"""
Script de test rapide pour le graphe agent (Phase 2).
À lancer depuis la racine du repo : python test_agent.py
Assure-toi que backend/.env contient OPENAI_API_KEY et DATABASE_URL.
"""
import asyncio
import sys
from pathlib import Path

# Windows: psycopg requires SelectorEventLoop, not ProactorEventLoop
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Add backend to path so we can import app
backend = Path(__file__).resolve().parent / "backend"
sys.path.insert(0, str(backend))


def _checkpoint_conn_string() -> str:
    import os
    url = os.getenv(
        "CHECKPOINT_DATABASE_URL",
        os.getenv(
            "DATABASE_URL",
            "postgresql://volteyr:volteyr_dev@localhost:5432/volteyr",
        ),
    )
    if url.startswith("postgresql+asyncpg://"):
        url = "postgresql://" + url[len("postgresql+asyncpg://") :]
    return url


async def main() -> None:
    import os
    from langchain_core.messages import HumanMessage

    from app.agent.graph import get_graph_with_checkpointer

    config = {"configurable": {"thread_id": "123"}}
    input_messages = [HumanMessage(content="Bonjour !")]

    # Postgres checkpointer incompatible avec le pooler Supabase (port 6543) → DuplicatePreparedStatement.
    # On utilise la mémoire si :6543/ dans l'URL, ou si USE_MEMORY_CHECKPOINTER=1, ou pas de DB.
    db_url = os.getenv("CHECKPOINT_DATABASE_URL") or os.getenv("DATABASE_URL") or ""
    use_postgres = (
        not os.getenv("USE_MEMORY_CHECKPOINTER")
        and db_url
        and ":6543/" not in db_url  # Supabase transaction pooler = pas de prepared statements
    )
    if use_postgres:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        conn_string = _checkpoint_conn_string()
        async with AsyncPostgresSaver.from_conn_string(conn_string) as checkpointer:
            await checkpointer.setup()
            graph = get_graph_with_checkpointer(checkpointer)
            result = await graph.ainvoke({"messages": input_messages}, config=config)
    else:
        if db_url and ":6543/" in db_url:
            print("(Checkpointer en mémoire : pooler Supabase 6543 non compatible. Pour la persistance Postgres, utilise CHECKPOINT_DATABASE_URL avec le pooler session, port 5432.)")
        from langgraph.checkpoint.memory import InMemorySaver
        memory = InMemorySaver()
        graph = get_graph_with_checkpointer(memory)
        result = await graph.ainvoke({"messages": input_messages}, config=config)

    messages = result.get("messages", [])
    last = messages[-1] if messages else None
    if last is not None:
        print("Réponse:", last.content if hasattr(last, "content") else last)
    else:
        print("Aucun message dans le résultat:", result)


if __name__ == "__main__":
    asyncio.run(main())
