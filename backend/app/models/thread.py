"""
SQLAlchemy model for the `threads` table.
user_id matches Supabase auth.users.id (UUID).
"""
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base for all models."""

    pass


class Thread(Base):
    """
    Conversation thread. user_id references Supabase auth.users.id.
    RLS on this table ensures users only see their own threads.
    """

    __tablename__ = "threads"

    thread_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
        # No FK to auth.users: Supabase manages auth schema; RLS enforces ownership.
    )
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        server_default="{}",
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<Thread(thread_id={self.thread_id!r}, user_id={self.user_id!r})>"
