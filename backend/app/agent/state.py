"""
Agent state definition for the LangGraph brain.
Uses add_messages reducer so message history is appended, not overwritten.
"""
from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage

from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """State for the main agent graph. Messages stack via add_messages."""

    messages: Annotated[list[AnyMessage], add_messages]
