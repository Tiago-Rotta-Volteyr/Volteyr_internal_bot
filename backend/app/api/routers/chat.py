"""
Chat API: streaming endpoint and human-in-the-loop resume.
"""
import asyncio
import logging
import uuid
from typing import Annotated, Any, AsyncGenerator

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.responses import Response, StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tracers.stdout import ConsoleCallbackHandler
from langgraph.types import Command
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.graph import get_graph
from app.api.deps import User, get_current_user
from app.core.database import get_db
from app.models import Thread
from app.services.titling import generate_chat_title

LOG = logging.getLogger(__name__)
FIRST_CHAT = "[FIRST-CHAT]"

router = APIRouter(prefix="/chat", tags=["chat"])


# --- Request/Response models ---


class ChatMessage(BaseModel):
    """One message in the chat (Vercel AI SDK–style)."""

    role: str = Field(..., description="'user' or 'assistant' or 'system'")
    content: str = Field(default="", description="Text content")


class ChatRequest(BaseModel):
    """POST /api/chat body."""

    messages: list[ChatMessage] = Field(..., description="Conversation history")
    thread_id: str | None = Field(default=None, description="Existing thread UUID or omit for new thread")


class ResumeRequest(BaseModel):
    """POST /api/chat/resume body (HITL approval)."""

    thread_id: str = Field(..., description="Thread where the graph is paused")
    action: str = Field(..., description="'approve' or 'reject'")


# --- Helpers ---


def _state_messages_to_api(messages: list) -> list[dict[str, str]]:
    """Convert LangChain state messages to API format (user/assistant only, with content)."""
    out: list[dict[str, str]] = []
    for m in messages or []:
        role: str | None = None
        if isinstance(m, HumanMessage):
            role = "user"
        elif isinstance(m, AIMessage):
            role = "assistant"
        if role is not None:
            content = getattr(m, "content", None)
            out.append({"role": role, "content": content if isinstance(content, str) else (str(content) if content else "")})
    return out


def _to_langchain_messages(messages: list[ChatMessage]) -> list:
    """Convert API messages to LangChain messages (HumanMessage / AIMessage)."""
    out = []
    for m in messages:
        content = m.content or ""
        if m.role == "user":
            out.append(HumanMessage(content=content))
        elif m.role == "assistant":
            out.append(AIMessage(content=content))
        # skip "system" for history; system prompt is injected in the graph
    return out


# Placeholder title for client-created threads until auto-titling runs
NEW_CHAT_TITLE = "New Chat"


async def _ensure_thread(
    db: AsyncSession,
    user: User,
    thread_id: str | None,
) -> uuid.UUID:
    """
    If thread_id is provided: verify it belongs to user, or create it (client-side ID).
    If not provided, insert a new thread with server-generated id and return it.
    """
    user_uuid = uuid.UUID(user.id)

    if thread_id:
        try:
            thread_uuid = uuid.UUID(thread_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid thread_id format",
            ) from None
        result = await db.execute(select(Thread).where(Thread.thread_id == thread_uuid))
        thread = result.scalar_one_or_none()
        if thread:
            if thread.user_id != user_uuid:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Thread not found or access denied",
                )
            return thread.thread_id
        # Client-provided ID but not in DB: create thread (or race: POST /api/chat just created it)
        thread = Thread(
            thread_id=thread_uuid,
            user_id=user_uuid,
            title=NEW_CHAT_TITLE,
            metadata_={},
        )
        db.add(thread)
        try:
            await db.commit()
            await db.refresh(thread)
            return thread.thread_id
        except IntegrityError:
            await db.rollback()
            result = await db.execute(select(Thread).where(Thread.thread_id == thread_uuid))
            thread = result.scalar_one_or_none()
            if thread and thread.user_id == user_uuid:
                return thread.thread_id
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Thread not found or access denied",
            )

    # No thread_id: new thread with server-generated id
    thread = Thread(
        user_id=user_uuid,
        title=None,
        metadata_={},
    )
    db.add(thread)
    await db.commit()
    await db.refresh(thread)
    return thread.thread_id


def _chunk_content_to_str(content: Any) -> str:
    """Extract plain text from chunk.content (string or list of content blocks)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(str(c) for c in content if c)
    return ""


async def _event_stream(
    input_state: dict[str, Any],
    config: dict[str, Any],
) -> AsyncGenerator[bytes, None]:
    """
    Filtre STRICT des événements LangGraph : on n'envoie que le texte brut du LLM.
    Pas de JSON, pas d'événements bruts — uniquement le contenu des tokens pour le frontend.
    """
    graph = await get_graph()

    thread_id = config.get("configurable", {}).get("thread_id", "")
    LOG.info("%s stream START thread_id=%s", "[FLOW]", thread_id)
    chunk_count = 0
    try:
        async for event in graph.astream_events(
            input_state,
            config=config,
            version="v1",
        ):
            kind = event["event"]

            if kind == "on_chat_model_stream":
                content = event["data"]["chunk"].content
                content = _chunk_content_to_str(content)
                if content:
                    chunk_count += 1
                    yield content.encode("utf-8")
        LOG.info("%s stream END chunk_count=%s", "[FLOW]", chunk_count)
    except asyncio.CancelledError:
        raise
    except Exception:
        yield "\n\nUne erreur est survenue. Réessayez.".encode("utf-8")


# --- Endpoints ---


@router.post("")
async def chat_stream(
    body: ChatRequest,
    background_tasks: BackgroundTasks,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Stream assistant reply for the given messages and optional thread_id.
    Uses Vercel AI SDK–compatible SSE (x-vercel-ai-ui-message-stream: v1).
    On HITL interrupt, sends a data-hitl-pause part so the frontend can show Approve/Reject.
    """
    LOG.info("%s demande reçue thread_id=%s messages=%s", "[FLOW]", body.thread_id, len(body.messages or []))
    thread_uuid = await _ensure_thread(db, current_user, body.thread_id)
    config = {"configurable": {"thread_id": str(thread_uuid)}}

    # Auto-titling: first message or thread still has no title
    current_title = None
    if body.thread_id:
        r = await db.execute(select(Thread.title).where(Thread.thread_id == thread_uuid))
        row = r.one_or_none()
        current_title = row[0] if row else None
    should_title = (
        body.thread_id is None
        or current_title is None
        or (current_title or "").strip() == "New Chat"
    )
    first_message_content = (body.messages[-1].content or "").strip() if body.messages else ""
    if should_title and first_message_content:
        background_tasks.add_task(generate_chat_title, first_message_content, str(thread_uuid))

    lc_messages = _to_langchain_messages(body.messages)
    if not lc_messages:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one message is required",
        )
    # Existing thread: checkpoint already has history; only append the latest message.
    if body.thread_id:
        lc_messages = lc_messages[-1:]
    input_state: dict[str, Any] = {"messages": lc_messages}

    async def generate() -> AsyncGenerator[bytes, None]:
        async for chunk_bytes in _event_stream(input_state, config):
            yield chunk_bytes

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Vercel-AI-UI-Message-Stream": "v1",
            "X-Thread-Id": str(thread_uuid),
        },
    )


class ThreadListItem(BaseModel):
    """One thread in the list for GET /threads."""

    thread_id: str
    title: str | None
    created_at: str


@router.get("/threads", response_model=list[ThreadListItem])
async def list_threads(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Return the list of threads for the current user (for sidebar).
    Ordered by created_at descending.
    """
    user_uuid = uuid.UUID(current_user.id)
    result = await db.execute(
        select(Thread)
        .where(Thread.user_id == user_uuid)
        .order_by(Thread.created_at.desc())
    )
    threads = result.scalars().all()
    return [
        ThreadListItem(
            thread_id=str(t.thread_id),
            title=t.title,
            created_at=t.created_at.isoformat() if t.created_at else "",
        )
        for t in threads
    ]


@router.get("/history")
async def chat_history(
    thread_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Return message history for a thread (user + assistant only).
    Used by the frontend to restore conversation on reload or when switching threads.
    For new threads (no checkpoint yet), returns empty messages instead of 404/500.
    """
    LOG.info("%s GET /history IN thread_id=%s", FIRST_CHAT, thread_id)
    thread_uuid = await _ensure_thread(db, current_user, thread_id)
    config = {"configurable": {"thread_id": str(thread_uuid)}}
    try:
        graph = await get_graph()
        state = await graph.aget_state(config)
    except Exception as e:
        LOG.info("%s GET /history no state (new thread?) → [] %s", FIRST_CHAT, type(e).__name__)
        return {"messages": []}
    if not state or not state.values:
        LOG.info("%s GET /history state empty → []", FIRST_CHAT)
        return {"messages": []}
    messages = state.values.get("messages") or []
    count = len(messages)
    LOG.info("%s GET /history OUT messages_count=%s", FIRST_CHAT, count)
    return {"messages": _state_messages_to_api(messages)}


@router.post("/resume")
async def chat_resume(
    body: ResumeRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Resume the graph after a human-in-the-loop pause (e.g. approve or reject email).
    Ensures the thread belongs to the current user, then invokes the graph with Command(resume=action).
    """
    if body.action not in ("approve", "reject"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="action must be 'approve' or 'reject'",
        )

    LOG.info("%s POST /resume IN thread_id=%s action=%s", "[FLOW]", body.thread_id, body.action)
    thread_uuid = await _ensure_thread(db, current_user, body.thread_id)
    config = {"configurable": {"thread_id": str(thread_uuid)}}

    graph = await get_graph()
    try:
        result = await graph.ainvoke(
            Command(resume=body.action),
            config=config,
        )
    except Exception as e:
        LOG.warning("%s POST /resume FAILED thread_id=%s error=%s", "[FLOW]", body.thread_id, e)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Resume failed: {e!s}",
        ) from e

    msg_count = len(result.get("messages", []))
    LOG.info("%s POST /resume OUT thread_id=%s action=%s messages_count=%s", "[FLOW]", str(thread_uuid), body.action, msg_count)
    return {
        "status": "resumed",
        "thread_id": str(thread_uuid),
        "action": body.action,
        "messages_count": msg_count,
    }


@router.delete("/threads/{thread_id}")
async def delete_thread(
    thread_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Delete a conversation thread. Only the owner can delete (403 otherwise).
    Returns 204 No Content on success.
    """
    user_uuid = uuid.UUID(current_user.id)
    try:
        thread_uuid = uuid.UUID(thread_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid thread_id") from None
    result = await db.execute(
        select(Thread).where(
            Thread.thread_id == thread_uuid,
            Thread.user_id == user_uuid,
        )
    )
    thread = result.scalar_one_or_none()
    if not thread:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Thread not found or access denied",
        )
    await db.execute(delete(Thread).where(Thread.thread_id == thread_uuid))
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
