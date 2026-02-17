import os
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routers import auth as auth_router
from app.api.routers import chat as chat_router
from app.core.database import async_engine, get_db
from app.models import Base, Thread


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize DB on startup (create tables when running locally). Shutdown: dispose engine."""
    if os.getenv("DB_CREATE_TABLES", "false").lower() == "true":
        async with async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    yield
    await async_engine.dispose()


app = FastAPI(title="Volteyr API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router.router, prefix="/api")
app.include_router(chat_router.router, prefix="/api")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/test-db")
async def test_db(db: AsyncSession = Depends(get_db)) -> dict:
    """Insert a dummy thread for DB connectivity test. Uses an existing auth.users id on Supabase."""
    try:
        # Supabase: threads.user_id has FK to auth.users(id). Use an existing user or fail with a clear message.
        user_id: UUID | None = None
        try:
            result = await db.execute(text("SELECT id FROM auth.users LIMIT 1"))
            user_id = result.scalar_one_or_none()
        except Exception:
            pass  # auth.users may not exist (e.g. local Docker) → use random uuid below
        if user_id is None:
            # Local dev without auth schema: use random id (works only if table has no FK to auth.users).
            user_id = uuid4()
            # If we're on Supabase and no user exists, the insert will fail with FK violation;
            # we'll catch it and return a hint.
        thread = Thread(
            user_id=user_id,
            title="Test thread",
            metadata_={},
        )
        db.add(thread)
        await db.commit()
        await db.refresh(thread)
        return {
            "thread_id": str(thread.thread_id),
            "user_id": str(thread.user_id),
            "title": thread.title,
            "created_at": thread.created_at.isoformat() if thread.created_at else None,
        }
    except Exception as e:  # noqa: BLE001
        await db.rollback()
        err_msg = str(e)
        if "ForeignKeyViolationError" in err_msg or "foreign key" in err_msg.lower():
            return JSONResponse(
                status_code=400,
                content={
                    "detail": "No user in auth.users. Create at least one user in Supabase Auth (e.g. sign up once in your app or via Dashboard → Authentication), then retry POST /test-db.",
                    "error": err_msg,
                },
            )
        return JSONResponse(
            status_code=500,
            content={"detail": "Database error", "error": err_msg},
        )
