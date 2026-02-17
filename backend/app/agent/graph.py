"""
LangGraph brain: StateGraph, agent node, and persistent checkpointer.
"""
import os
from typing import Any

from dotenv import load_dotenv
from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.agent.prompts import build_system_prompt
from app.agent.state import AgentState
from app.tools.airtable import search_airtable
from app.tools.email import send_email
from app.tools.retrieval import lookup_policy
from app.tools.utils import get_table_schema

load_dotenv()

# Checkpointer lifecycle: pool and saver kept in module scope so the compiled graph stays valid.
_pool: AsyncConnectionPool | None = None
_compiled_graph: Any = None


def _checkpoint_conn_string() -> str:
    """
    Build Postgres connection string for psycopg (langgraph-checkpoint-postgres).
    Prefer CHECKPOINT_DATABASE_URL if set (e.g. session pooler on 5432);
    Supabase transaction pooler (port 6543) can cause DuplicatePreparedStatement,
    so use session pooler for the checkpointer when possible.
    """
    url = os.getenv(
        "CHECKPOINT_DATABASE_URL",
        os.getenv(
            "DATABASE_URL",
            "postgresql+asyncpg://volteyr:volteyr_dev@localhost:5432/volteyr",
        ),
    )
    # langgraph checkpoint uses psycopg, which expects postgresql:// (no +asyncpg)
    if url.startswith("postgresql+asyncpg://"):
        url = "postgresql://" + url[len("postgresql+asyncpg://") :]
    return url


def _build_graph() -> StateGraph:
    """Build the StateGraph (no checkpointer). Used by get_graph / get_graph_with_checkpointer."""
    meta_schema = get_table_schema()
    system_prompt = build_system_prompt(airtable_schema=meta_schema)

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0).bind_tools([search_airtable, lookup_policy, send_email])

    async def call_model(state: AgentState) -> dict[str, Any]:
        messages = [SystemMessage(content=system_prompt)] + state["messages"]
        response = await llm.ainvoke(messages)
        return {"messages": [response]}

    def _run_tool(name: str, args: dict) -> str:
        try:
            if name == "search_airtable":
                return search_airtable.invoke(args)
            if name == "lookup_policy":
                return lookup_policy.invoke(args)
            if name == "send_email":
                return send_email.invoke(args)
            return f"Unknown tool: {name}"
        except Exception as e:
            return f"Error running {name}: {e!s}"

    async def run_tools(state: AgentState) -> dict[str, Any]:
        from langchain_core.messages import ToolMessage

        last = state["messages"][-1]
        tool_messages = []
        if hasattr(last, "tool_calls") and last.tool_calls:
            for tc in last.tool_calls:
                name = tc.get("name")
                args = tc.get("args") or {}
                out = _run_tool(name or "", args)
                tool_messages.append(
                    ToolMessage(content=str(out), tool_call_id=tc.get("id", ""))
                )
        return {"messages": tool_messages}

    async def run_tools_email(state: AgentState) -> dict[str, Any]:
        """Run only send_email tool calls (used after HITL approval). Other tools are no-op."""
        from langchain_core.messages import ToolMessage

        last = state["messages"][-1]
        tool_messages = []
        if hasattr(last, "tool_calls") and last.tool_calls:
            for tc in last.tool_calls:
                name = tc.get("name")
                args = tc.get("args") or {}
                if name == "send_email":
                    out = _run_tool(name, args)
                else:
                    out = f"Skipped (not email): {name}"
                tool_messages.append(
                    ToolMessage(content=str(out), tool_call_id=tc.get("id", ""))
                )
        return {"messages": tool_messages}

    # Rate limit: max tool invocations per turn to avoid infinite retry loops
    MAX_TOOL_MESSAGES = 10

    def should_continue(state: AgentState) -> str:
        from langchain_core.messages import ToolMessage

        last = state["messages"][-1]
        if not hasattr(last, "tool_calls") or not last.tool_calls:
            return "end"
        tool_count = sum(1 for m in state["messages"] if isinstance(m, ToolMessage))
        if tool_count >= MAX_TOOL_MESSAGES:
            return "end"
        names = [tc.get("name") for tc in last.tool_calls if tc.get("name")]
        if "send_email" in names:
            return "tools_email"
        return "tools"

    graph = StateGraph(AgentState)
    graph.add_node("agent", call_model)
    graph.add_node("tools", run_tools)
    graph.add_node("tools_email", run_tools_email)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges(
        "agent", should_continue, {"tools": "tools", "tools_email": "tools_email", "end": END}
    )
    graph.add_edge("tools", "agent")
    graph.add_edge("tools_email", "agent")
    return graph


async def get_graph():
    """
    Initialize the Postgres checkpointer from DATABASE_URL and return the compiled graph.
    Uses a module-level connection pool so the graph can be reused (e.g. in FastAPI).
    """
    global _pool, _compiled_graph
    if _compiled_graph is not None:
        return _compiled_graph

    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    conn_string = _checkpoint_conn_string()
    _pool = AsyncConnectionPool(
        conninfo=conn_string,
        max_size=10,
        kwargs={
            "autocommit": True,
            "prepare_threshold": 0,
            "row_factory": dict_row,
        },
        open=False,
    )
    await _pool.open()
    # AsyncPostgresSaver accepts a pool; it uses get_connection() internally
    checkpointer = AsyncPostgresSaver(conn=_pool)
    await checkpointer.setup()
    _compiled_graph = _build_graph().compile(
        checkpointer=checkpointer, interrupt_before=["tools_email"]
    )
    return _compiled_graph


def get_graph_with_checkpointer(checkpointer: Any):
    """
    Compile and return the graph with the given checkpointer.
    Useful for tests or when the caller manages the checkpointer (e.g. from_conn_string).
    """
    return _build_graph().compile(
        checkpointer=checkpointer, interrupt_before=["tools_email"]
    )
