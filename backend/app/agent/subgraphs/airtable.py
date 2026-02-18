"""
Airtable sub-agent: self-correcting StateGraph that retries on API/column errors (max 3).
The LLM reads "Error: ..." as observation and can correct table/field names.
"""
import logging
from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.graph.message import add_messages
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from app.core.config import AIRTABLE_BASE_ID, AIRTABLE_API_KEY, AIRTABLE_TABLE_NAMES
from app.tools.airtable import search_airtable
from app.tools.utils import (
    fetch_all_tables_metadata,
    get_relations_schema,
    get_table_schema,
    get_table_schema_formatted,
)
from app.agent.prompts import get_airtable_agent_prompt

FLOW = "[FLOW]"
LOG = logging.getLogger(__name__)

# Subgraph state: messages (append) + retry counter
class AirtableSubgraphState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    retries_used: int


AIRTABLE_MAX_RETRIES = 3


def _airtable_system_prompt() -> str:
    # Tables découvertes via l'API Metadata (ou fallback AIRTABLE_TABLE_NAMES)
    dynamic_table_list = fetch_all_tables_metadata(AIRTABLE_BASE_ID, AIRTABLE_API_KEY)
    if not dynamic_table_list:
        dynamic_table_list = list(AIRTABLE_TABLE_NAMES or [])
    table_list = (
        ", ".join(f"'{t}'" for t in dynamic_table_list)
        if dynamic_table_list
        else "(aucune table configurée)"
    )

    # Table "active" pour le schéma colonnes : préférer une table dont le nom contient "Client", sinon la première
    client_table = next(
        (t for t in dynamic_table_list if "client" in t.lower()),
        dynamic_table_list[0] if dynamic_table_list else "Client",
    )
    table_schema = get_table_schema_formatted(client_table)
    schema_section = (
        table_schema.strip()
        if table_schema.strip()
        else "(schéma non disponible — utilise les noms de champs indiqués dans les erreurs.)"
    )

    relations_section = get_relations_schema()
    base_prompt = get_airtable_agent_prompt(
        schema_section=schema_section,
        table_list=table_list,
        relations_section=relations_section,
    )
    # Complément : schéma complet des autres tables + règle de retry
    full_schema = get_table_schema()
    return f"""{base_prompt}

---

**Schéma complet (toutes les tables) :**
{full_schema}

**Règle** : Tu as au plus {AIRTABLE_MAX_RETRIES} tentatives en cas d'erreur ; après ça, renvoie une synthèse de l'erreur à l'utilisateur. Si l'outil renvoie "Error:" (champ introuvable, etc.), lis le message et réessaie avec un champ ou une table valide."""


def _build_airtable_graph() -> StateGraph:
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0).bind_tools([search_airtable])

    def agent_node(state: AirtableSubgraphState) -> dict[str, Any]:
        user_content = ""
        if state["messages"]:
            last = state["messages"][-1]
            user_content = (getattr(last, "content", None) or "")[:200]
        LOG.info("%s airtable_subgraph agent IN user_content_preview=%s", FLOW, user_content[:100] if user_content else "")
        messages = [SystemMessage(content=_airtable_system_prompt())] + state["messages"]
        response = llm.invoke(messages)
        tool_calls = getattr(response, "tool_calls", None) or []
        if tool_calls:
            LOG.info("%s airtable_subgraph agent OUT tool_calls=%s args=%s", FLOW, [t.get("name") for t in tool_calls], [t.get("args") for t in tool_calls])
        else:
            content_preview = (getattr(response, "content", None) or "")[:150]
            LOG.info("%s airtable_subgraph agent OUT end (no tool_calls) content_preview=%s", FLOW, content_preview[:80] if content_preview else "")
        return {"messages": [response]}

    tools = [search_airtable]
    tool_node = ToolNode(tools)

    def tool_node_wrapper(state: AirtableSubgraphState) -> dict[str, Any]:
        # Log de la requête complète (args envoyés à search_airtable)
        last_msg = state["messages"][-1] if state["messages"] else None
        if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
            for tc in last_msg.tool_calls:
                a = tc.get("args") or {}
                LOG.info("%s Airtable (sous-graphe): query complète → table=%s query=%s formula=%s sort_by=%s sort_direction=%s max_records=%s", FLOW, a.get("table_name"), a.get("query"), a.get("formula"), a.get("sort_by"), a.get("sort_direction"), a.get("max_records"))
        else:
            LOG.info("%s Airtable (sous-graphe): outil search_airtable appelé", FLOW)
        out = tool_node.invoke(state)
        last_content = ""
        if out.get("messages"):
            last_msg = out["messages"][-1]
            if isinstance(last_msg, ToolMessage):
                last_content = (last_msg.content or "") if isinstance(last_msg.content, str) else str(last_msg.content)
        if "Error" in last_content or "error" in last_content.lower():
            LOG.info("%s Airtable (sous-graphe): recherche → erreur", FLOW)
        elif "No records" in last_content or not last_content.strip():
            LOG.info("%s Airtable (sous-graphe): recherche → aucun enregistrement", FLOW)
        else:
            lines = last_content.count("\n") + 1
            LOG.info("%s Airtable (sous-graphe): recherche → %s", FLOW, f"{lines} lignes ressorties" if lines > 1 else "1 ligne ressortie")
        is_error = "Error" in last_content or "error" in last_content.lower()
        retries = state.get("retries_used", 0)
        new_retries = retries + 1 if is_error else retries
        return {"messages": out["messages"], "retries_used": new_retries}

    def after_tool_route(state: AirtableSubgraphState) -> Literal["agent", "__end__"]:
        last = state["messages"][-1] if state["messages"] else None
        if not isinstance(last, ToolMessage):
            return "__end__"
        content = (last.content or "") if isinstance(last.content, str) else str(last.content)
        is_error = "Error" in content or "error" in content.lower()
        retries = state.get("retries_used", 0)
        if is_error and retries < AIRTABLE_MAX_RETRIES:
            return "agent"
        return "__end__"

    graph = StateGraph(AirtableSubgraphState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_node_wrapper)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", _tools_condition, {"tools": "tools", "__end__": END})
    graph.add_conditional_edges("tools", after_tool_route, {"agent": "agent", "__end__": END})
    return graph


def _tools_condition(state: AirtableSubgraphState) -> Literal["tools", "__end__"]:
    last = state["messages"][-1] if state["messages"] else None
    if not isinstance(last, AIMessage) or not getattr(last, "tool_calls", None):
        return "__end__"
    return "tools"


def get_airtable_graph():
    """Compiled Airtable subgraph (no checkpointer). Invoke with state = { messages: [HumanMessage(...)], retries_used: 0 }."""
    return _build_airtable_graph().compile()
