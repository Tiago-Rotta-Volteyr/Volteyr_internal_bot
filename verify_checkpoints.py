"""
Vérifie que les checkpoints du chat sont bien enregistrés dans Supabase.
À lancer depuis backend/ : python ..\verify_checkpoints.py
"""
import asyncio
import os
import sys
from pathlib import Path

# Add backend to path
backend = Path(__file__).resolve().parent / "backend"
sys.path.insert(0, str(backend))

# Load .env from backend
from dotenv import load_dotenv
load_dotenv(backend / ".env")


def _conn_string() -> str:
    url = os.getenv(
        "CHECKPOINT_DATABASE_URL",
        os.getenv("DATABASE_URL", ""),
    )
    if not url:
        print("Aucun CHECKPOINT_DATABASE_URL ou DATABASE_URL trouvé.")
        sys.exit(1)
    if url.startswith("postgresql+asyncpg://"):
        url = "postgresql://" + url[len("postgresql+asyncpg://") :]
    return url


async def main() -> None:
    from psycopg import AsyncConnection
    from psycopg.rows import dict_row

    conn_string = _conn_string()
    try:
        conn = await AsyncConnection.connect(
            conn_string,
            autocommit=True,
            row_factory=dict_row,
        )
        async with conn:
            async with conn.cursor() as cur:
                # Tables créées par LangGraph
                await cur.execute("""
                    SELECT table_name FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_name LIKE 'checkpoint%'
                    ORDER BY table_name
                """)
                tables = [row["table_name"] for row in await cur.fetchall()]
                if not tables:
                    print("Aucune table checkpoint trouvée. Le checkpointer n'a peut-être pas encore été utilisé.")
                    return
                print("Tables checkpoint:", ", ".join(tables))

                # Nombre de checkpoints par thread
                await cur.execute("""
                    SELECT thread_id, COUNT(*) as nb
                    FROM checkpoints
                    GROUP BY thread_id
                    ORDER BY thread_id
                """)
                rows = await cur.fetchall()
                if not rows:
                    print("Aucun checkpoint en base.")
                    return
                print("\nCheckpoints par thread_id:")
                for row in rows:
                    print(f"  thread_id = {row['thread_id']!r}  ->  {row['nb']} checkpoint(s)")

                # Détail pour le thread "123" (celui du test_agent.py)
                await cur.execute(
                    "SELECT thread_id, checkpoint_ns, checkpoint_id FROM checkpoints WHERE thread_id = %s",
                    ("123",),
                )
                detail = await cur.fetchall()
                if detail:
                    print(f"\nDétail pour thread_id '123' (test_agent.py):")
                    for r in detail:
                        print(f"  checkpoint_id = {r['checkpoint_id']}")
                else:
                    print("\nAucun checkpoint pour thread_id '123'. Lance d'abord: .venv\\Scripts\\python ..\\test_agent.py")
    except Exception as e:
        print("Erreur:", e)
        sys.exit(1)


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
