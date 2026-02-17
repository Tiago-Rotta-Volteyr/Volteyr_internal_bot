"""
Database configuration: async engine and session.
Works with both local Docker Postgres and Supabase (session or transaction pooler).
"""
import os
import ssl
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

# Load env for DATABASE_URL
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://volteyr:volteyr_dev@localhost:5432/volteyr",
)

# Supabase (incl. pooler: *.pooler.supabase.com:6543) requires SSL. Port 6543 = transaction pooler → NullPool.
_is_supabase = "supabase.co" in DATABASE_URL or "supabase.com" in DATABASE_URL

_connect_args: dict = {}
if _is_supabase:
    # If SSL verification fails (e.g. corporate proxy, Windows cert store), set DB_SSL_VERIFY=false (dev only).
    if os.getenv("DB_SSL_VERIFY", "true").lower() == "false":
        _ctx = ssl.create_default_context()
        _ctx.check_hostname = False
        _ctx.verify_mode = ssl.CERT_NONE
        _connect_args["ssl"] = _ctx
    else:
        _connect_args["ssl"] = True

# Transaction pooler (e.g. Supabase port 6543 / pgbouncer) does not support prepared statements.
# Use NullPool + statement_cache_size=0 so asyncpg does not cache prepared statements.
_use_null_pool = ":6543/" in DATABASE_URL
if _use_null_pool:
    _connect_args["statement_cache_size"] = 0

if _use_null_pool:
    _engine = create_async_engine(
        DATABASE_URL,
        echo=os.getenv("SQL_ECHO", "false").lower() == "true",
        connect_args=_connect_args,
        poolclass=NullPool,
    )
else:
    _engine = create_async_engine(
        DATABASE_URL,
        echo=os.getenv("SQL_ECHO", "false").lower() == "true",
        connect_args=_connect_args,
        pool_size=5,
        max_overflow=10,
    )

# Expose engine for lifespan (e.g. create tables when running locally).
async_engine = _engine

AsyncSessionLocal = async_sessionmaker(
    _engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency: yield an async session. Caller is responsible for commit/rollback."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
