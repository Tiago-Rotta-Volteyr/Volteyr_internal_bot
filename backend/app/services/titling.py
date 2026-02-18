"""
Auto-titling: generate a short title for a thread from the first user message.
Runs in background (fire-and-forget); failures are logged and do not block chat.
"""
import logging
import uuid

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from sqlalchemy import update

from app.core.database import AsyncSessionLocal
from app.models import Thread

logger = logging.getLogger(__name__)

TITLING_PROMPT = (
    "Génère un titre très court (3 à 5 mots maximum), sans guillemets, "
    "résumant ce message : '{first_message}'."
)


async def generate_chat_title(first_message: str, thread_id: str) -> None:
    """
    Generate a short title from the first user message and update the thread in DB.
    Uses its own DB session (for use in BackgroundTasks). Errors are caught and logged.
    """
    first_message = (first_message or "").strip()
    if not first_message:
        return
    try:
        thread_uuid = uuid.UUID(thread_id)
    except (ValueError, TypeError):
        return

    async with AsyncSessionLocal() as db:
        try:
            llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
            prompt = TITLING_PROMPT.format(first_message=first_message[:500])
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            title = (getattr(response, "content", None) or "").strip()
            if not title:
                return
            await db.execute(
                update(Thread).where(Thread.thread_id == thread_uuid).values(title=title)
            )
            await db.commit()
        except Exception as e:
            logger.exception("titling failed for thread_id=%s: %s", thread_id, e)
            await db.rollback()
