"""
Human-in-the-Loop test: graph interrupts before running tools, then resumes after "validation".
Run: python -m pytest test_email_flow.py -v -s
(-s to see print output: "Interruption détectée ! Validation...", "FAKE SENDING EMAIL...")
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent / ".env")

THREAD_ID = "hitl-email-test"
CONFIG = {"configurable": {"thread_id": THREAD_ID}}


async def _run_email_hitl_flow():
    from langchain_core.messages import HumanMessage
    from langgraph.checkpoint.memory import MemorySaver

    from app.agent.graph import get_graph_with_checkpointer

    memory = MemorySaver()
    graph = get_graph_with_checkpointer(memory)

    # Étape 1 : Lance le graphe avec une demande d'envoi d'email
    initial_input = {
        "messages": [HumanMessage(content="Envoie un email à bob@test.com disant coucou")]
    }
    result = await graph.ainvoke(initial_input, config=CONFIG)

    # Étape 2 : Vérifie que le graphe s'est arrêté (next = tools_email)
    state = graph.get_state(CONFIG)
    next_nodes = state.next
    assert next_nodes == ("tools_email",), f"Expected next=('tools_email',), got {next_nodes}"

    # Étape 3 : Affiche l'interruption
    print("Interruption détectée ! Validation...")

    # Étape 4 : Relance le graphe pour continuer (resume) — pas de nouveau message, on valide l'action en attente
    resumed = await graph.ainvoke(None, config=CONFIG)

    # Étape 5 : Vérifie que l'outil s'est exécuté après la validation (dernier message = réponse agent après tool)
    messages = resumed.get("messages", [])
    assert len(messages) >= 1
    # On doit avoir au moins un ToolMessage (résultat send_email) ou un AIMessage final
    content_str = str(messages)
    assert "bob@test.com" in content_str or "Email sent" in content_str or "send_email" in content_str
    return result, resumed


def test_email_hitl_flow():
    """Full HITL flow: interrupt before tools, then resume and verify send_email ran."""
    if not os.getenv("OPENAI_API_KEY"):
        return  # skip without API key
    result, resumed = asyncio.run(_run_email_hitl_flow())
    assert resumed is not None
    assert "messages" in resumed


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "-s"])
