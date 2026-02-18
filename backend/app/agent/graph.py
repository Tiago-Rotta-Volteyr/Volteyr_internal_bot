"""
LangGraph brain: StateGraph, agent node, and persistent checkpointer.
"""
import asyncio
import json
import logging
import os
from typing import Any

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.agent.prompts import get_airtable_agent_prompt
from app.agent.state import AgentState
from app.agent.subgraphs.airtable import get_airtable_graph
from app.core.config import AIRTABLE_BASE_ID, AIRTABLE_API_KEY, AIRTABLE_TABLE_NAMES
from app.tools.airtable import search_airtable
from app.tools.email import send_email
from app.tools.retrieval import lookup_policy
from app.tools.utils import fetch_all_tables_metadata, get_table_schema_formatted

load_dotenv()

FLOW = "[FLOW]"
LOG = logging.getLogger(__name__)

# Message when a previous turn had tool_calls but no tool response (interrupt/crash)
_TOOL_INTERRUPTED_PLACEHOLDER = (
    "Error: the previous action was interrupted. Please try again or rephrase your request."
)


def _sanitize_messages_for_llm(messages: list) -> list:
    """
    Ensure every AIMessage with tool_calls has corresponding ToolMessages.
    If the checkpoint has an assistant message with tool_calls but no (or incomplete) tool
    responses (e.g. after HITL interrupt or crash), inject placeholder ToolMessages so
    the OpenAI API does not return 400.
    """
    result: list[Any] = []
    i = 0
    while i < len(messages):
        msg = messages[i]
        result.append(msg)
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            ids_expected = {tc.get("id") for tc in msg.tool_calls if tc.get("id")}
            ids_seen: set[str] = set()
            j = i + 1
            while j < len(messages):
                next_msg = messages[j]
                if isinstance(next_msg, ToolMessage):
                    tid = getattr(next_msg, "tool_call_id", None)
                    if tid in ids_expected:
                        ids_seen.add(tid or "")
                    result.append(next_msg)
                    j += 1
                else:
                    break
            missing = {x for x in (ids_expected - ids_seen) if x}
            for tid in missing:
                result.append(
                    ToolMessage(
                        content=_TOOL_INTERRUPTED_PLACEHOLDER,
                        tool_call_id=tid,
                    )
                )
            if missing:
                LOG.warning("%s sanitize: injected %s placeholder ToolMessage(s) for missing tool_call_ids", FLOW, len(missing))
            i = j
            continue
        i += 1
    return result

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
    dynamic_table_list = fetch_all_tables_metadata(AIRTABLE_BASE_ID, AIRTABLE_API_KEY)
    if not dynamic_table_list:
        dynamic_table_list = list(AIRTABLE_TABLE_NAMES or [])
    table_list = (
        ", ".join(f"'{t}'" for t in dynamic_table_list)
        if dynamic_table_list
        else "(aucune table configurée)"
    )
    client_table = next(
        (t for t in dynamic_table_list if "client" in t.lower()),
        dynamic_table_list[0] if dynamic_table_list else "Client",
    )
    schema_section = get_table_schema_formatted(client_table)
    if not schema_section.strip():
        schema_section = "(schéma non disponible — utilise les noms de champs indiqués dans les erreurs.)"
    system_prompt = get_airtable_agent_prompt(schema_section=schema_section, table_list=table_list)

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0).bind_tools([search_airtable, lookup_policy, send_email])

    async def call_model(state: AgentState) -> dict[str, Any]:
        nm = len(state["messages"])
        last_msg = state["messages"][-1] if state["messages"] else None
        last_preview = ""
        if last_msg and getattr(last_msg, "content", None):
            last_preview = (str(last_msg.content)[:200] + "…") if len(str(last_msg.content)) > 200 else str(last_msg.content)
        LOG.info("%s agent IN messages_count=%s last_preview=%s", FLOW, nm, last_preview[:100] if last_preview else "")
        messages = [SystemMessage(content=system_prompt)] + _sanitize_messages_for_llm(state["messages"])
        response = await llm.ainvoke(messages)
        tool_calls = getattr(response, "tool_calls", None) or []
        content_preview = (getattr(response, "content", None) or "")[:150] if getattr(response, "content", None) else ""
        if tool_calls:
            names = [tc.get("name") for tc in tool_calls if tc.get("name")]
            LOG.info("%s agent OUT tool_calls=%s", FLOW, names)
        else:
            LOG.info("%s agent OUT end (no tool_calls) content_preview=%s", FLOW, content_preview[:80] if content_preview else "")
        return {"messages": [response]}

    def _run_tool(name: str, args: dict) -> str:
        try:
            if name == "lookup_policy":
                return lookup_policy.invoke(args)
            if name == "send_email":
                return send_email.invoke(args)
            if name == "search_airtable":
                return _run_airtable_subgraph_sync(args)
            return f"Unknown tool: {name}"
        except Exception as e:
            return f"Error running {name}: {e!s}"

    def _run_airtable_subgraph_sync(args: dict) -> str:
        """Run Airtable subgraph (sync) and return final result string. Never raise."""
        try:
            table = args.get("table_name", "?")
            query = (args.get("query") or "").strip() or "(liste)"
            LOG.info("%s outil Airtable: appel recherche table=%s query=%s sort_by=%s sort_direction=%s max_records=%s", FLOW, table, query, args.get("sort_by"), args.get("sort_direction"), args.get("max_records"))
            airtable_graph = get_airtable_graph()
            query_desc = json.dumps(args, ensure_ascii=False) if args else "Query Airtable"
            initial_state: dict[str, Any] = {
                "messages": [HumanMessage(content=query_desc)],
                "retries_used": 0,
            }
            result = airtable_graph.invoke(initial_state)
            messages = result.get("messages") or []
            if not messages:
                LOG.info("%s outil Airtable: réponse → aucun enregistrement", FLOW)
                return "No records found."
            last = messages[-1]
            content = getattr(last, "content", None)
            out = content if isinstance(content, str) else str(content) if content is not None else ""
            out = out if out else "No records found."
            if "Error" in out or "error" in out.lower():
                LOG.info("%s outil Airtable: réponse → erreur", FLOW)
            elif "No records" in out or not out.strip():
                LOG.info("%s outil Airtable: réponse → aucun enregistrement", FLOW)
            else:
                lines = out.count("\n") + 1
                LOG.info("%s outil Airtable: réponse → %s (résultat reçu)", FLOW, f"{lines} lignes" if lines > 1 else "1 ligne")
            return out
        except Exception as e:
            LOG.warning("%s outil Airtable: erreur %s", FLOW, e)
            return f"Error executing tool: {e!s}"

    async def delegate_to_airtable(state: AgentState) -> dict[str, Any]:
        """Run Airtable subgraph for each search_airtable tool call; return ToolMessages for the main agent."""
        last = state["messages"][-1]
        tool_messages = []
        if hasattr(last, "tool_calls") and last.tool_calls:
            LOG.info("%s appel outil Airtable (sous-graphe)", FLOW)
            for tc in last.tool_calls:
                name = tc.get("name")
                if name != "search_airtable":
                    continue
                args = tc.get("args") or {}
                tool_call_id = tc.get("id", "")
                try:
                    out = await asyncio.to_thread(_run_airtable_subgraph_sync, args)
                    content = str(out) if out is not None else "No records found."
                except Exception as e:
                    content = f"Error executing tool: {e!s}"
                tool_messages.append(ToolMessage(content=content, tool_call_id=tool_call_id))
            LOG.info("%s Airtable → résultat reçu (%s réponse(s))", FLOW, len(tool_messages))
        return {"messages": tool_messages}

    async def run_tools(state: AgentState) -> dict[str, Any]:
        from langchain_core.messages import ToolMessage

        last = state["messages"][-1]
        tool_messages = []
        if hasattr(last, "tool_calls") and last.tool_calls:
            names = [tc.get("name") for tc in last.tool_calls if tc.get("name")]
            LOG.info("%s appel outils: %s", FLOW, names)
            for tc in last.tool_calls:
                name = tc.get("name")
                args = tc.get("args") or {}
                tool_call_id = tc.get("id", "")
                try:
                    if name == "search_airtable":
                        out = await asyncio.to_thread(_run_airtable_subgraph_sync, args)
                    else:
                        out = _run_tool(name or "", args)
                    content = str(out) if out is not None else "Error executing tool: no output."
                except Exception as e:
                    content = f"Error executing tool: {e!s}"
                tool_messages.append(ToolMessage(content=content, tool_call_id=tool_call_id))
            LOG.info("%s outils → réponses reçues (%s)", FLOW, len(tool_messages))
        return {"messages": tool_messages}

    async def run_tools_email(state: AgentState) -> dict[str, Any]:
        """Run only send_email tool calls (used after HITL approval). Other tools are no-op."""
        from langchain_core.messages import ToolMessage

        last = state["messages"][-1]
        tool_messages = []
        if hasattr(last, "tool_calls") and last.tool_calls:
            LOG.info("%s appel outil email (HITL approuvé)", FLOW)
            for tc in last.tool_calls:
                name = tc.get("name")
                args = tc.get("args") or {}
                tool_call_id = tc.get("id", "")
                try:
                    if name == "send_email":
                        out = _run_tool(name, args)
                    else:
                        out = f"Skipped (not email): {name}"
                    content = str(out) if out is not None else "Error executing tool: no output."
                except Exception as e:
                    content = f"Error executing tool: {e!s}"
                tool_messages.append(ToolMessage(content=content, tool_call_id=tool_call_id))
            LOG.info("%s email → envoyé", FLOW)
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
        if names and all(n == "search_airtable" for n in names):
            return "airtable"
        return "tools"

    graph = StateGraph(AgentState)
    graph.add_node("agent", call_model)
    graph.add_node("tools", run_tools)
    graph.add_node("tools_email", run_tools_email)
    graph.add_node("delegate_to_airtable", delegate_to_airtable)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges(
        "agent",
        should_continue,
        {"tools": "tools", "tools_email": "tools_email", "airtable": "delegate_to_airtable", "end": END},
    )
    graph.add_edge("tools", "agent")
    graph.add_edge("tools_email", "agent")
    graph.add_edge("delegate_to_airtable", "agent")
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
