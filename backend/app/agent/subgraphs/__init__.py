"""Sub-agents (subgraphs) for specialized skills with self-correction."""

from app.agent.subgraphs.airtable import get_airtable_graph

__all__ = ["get_airtable_graph"]
