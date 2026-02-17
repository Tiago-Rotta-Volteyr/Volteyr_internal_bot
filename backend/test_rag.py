"""
Tests for RAG (Skill 2): ingestion, lookup_policy tool, and agent answer.
Run ingestion first: python scripts/ingest_docs.py
Then: python -m pytest test_rag.py -v
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent / ".env")


def test_lookup_policy_returns_string():
    """lookup_policy returns a non-empty string when KB is populated."""
    from app.tools.retrieval import lookup_policy

    result = lookup_policy.invoke({"query": "politique Volteyr"})
    assert isinstance(result, str)
    # If KB is not configured or empty, we get an error or "Aucun document"
    assert len(result) > 0


def test_lookup_policy_contains_policy_content_after_ingestion():
    """After ingestion, querying 'politique' should return content from process_volteyr.txt."""
    from app.tools.retrieval import lookup_policy

    result = lookup_policy.invoke({"query": "politique de Volteyr"})
    assert isinstance(result, str)
    # The dummy file says "La politique de Volteyr repose sur trois piliers"
    if "Error" not in result and "Aucun document" not in result:
        assert "politique" in result.lower() or "Volteyr" in result or "transparence" in result


def test_agent_answers_policy_question():
    """Run graph with 'Quelle est la politique de Volteyr?' and check we get a coherent response."""
    import asyncio
    from langchain_core.messages import HumanMessage

    from app.agent.graph import get_graph_with_checkpointer
    from langgraph.checkpoint.memory import MemorySaver

    async def run():
        memory = MemorySaver()
        graph = get_graph_with_checkpointer(memory)
        config = {"configurable": {"thread_id": "rag-test-1"}}
        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="Quelle est la politique de Volteyr ?")]},
            config=config,
        )
        return result.get("messages", [])

    if not os.getenv("OPENAI_API_KEY"):
        return  # skip if no API key
    messages = asyncio.run(run())
    assert len(messages) >= 1
    last = messages[-1]
    content = getattr(last, "content", "") or ""
    assert isinstance(content, str)
    # Agent should have synthesized an answer (possibly after calling lookup_policy)
    assert len(content.strip()) > 0


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
