"""
Chat API: streaming endpoint and human-in-the-loop resume.
"""
import asyncio
import uuid
from typing import Annotated, Any, AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.graph import get_graph
from app.api.deps import User, get_current_user
from app.core.database import get_db
from app.models import Thread

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


async def _ensure_thread(
    db: AsyncSession,
    user: User,
    thread_id: str | None,
) -> uuid.UUID:
    """
    If thread_id is provided, verify it belongs to user (else 403).
    If not provided or new, insert a new thread and return its id.
    """
    user_uuid = uuid.UUID(user.id)

    if thread_id:
        result = await db.execute(
            select(Thread).where(
                Thread.thread_id == uuid.UUID(thread_id),
                Thread.user_id == user_uuid,
            )
        )
        thread = result.scalar_one_or_none()
        if not thread:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Thread not found or access denied",
            )
        return thread.thread_id

    # New thread: insert
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
                    yield content.encode("utf-8")
    except asyncio.CancelledError:
        raise
    except Exception:
        yield "\n\nUne erreur est survenue. Réessayez.".encode("utf-8")


# --- Endpoints ---


@router.post("")
async def chat_stream(
    body: ChatRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Stream assistant reply for the given messages and optional thread_id.
    Uses Vercel AI SDK–compatible SSE (x-vercel-ai-ui-message-stream: v1).
    On HITL interrupt, sends a data-hitl-pause part so the frontend can show Approve/Reject.
    """
    thread_uuid = await _ensure_thread(db, current_user, body.thread_id)
    config = {"configurable": {"thread_id": str(thread_uuid)}}

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


@router.get("/history")
async def chat_history(
    thread_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Return message history for a thread (user + assistant only).
    Used by the frontend to restore conversation on reload or when switching threads.
    """
    thread_uuid = await _ensure_thread(db, current_user, thread_id)
    config = {"configurable": {"thread_id": str(thread_uuid)}}
    graph = await get_graph()
    try:
        state = await graph.aget_state(config)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thread state not found: {e!s}",
        ) from e
    if not state or not state.values:
        return {"messages": []}
    messages = state.values.get("messages") or []
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

    thread_uuid = await _ensure_thread(db, current_user, body.thread_id)
    config = {"configurable": {"thread_id": str(thread_uuid)}}

    graph = await get_graph()
    try:
        result = await graph.ainvoke(
            Command(resume=body.action),
            config=config,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Resume failed: {e!s}",
        ) from e

    return {
        "status": "resumed",
        "thread_id": str(thread_uuid),
        "action": body.action,
        "messages_count": len(result.get("messages", [])),
    }
