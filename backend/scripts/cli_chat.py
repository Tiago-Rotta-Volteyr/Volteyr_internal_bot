"""
CLI to test the agent (e.g. "liste des clients"). Loads backend/.env and runs the graph.
Usage: python scripts/cli_chat.py "Donne-moi la liste des clients"
"""
import asyncio
import os
import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))
os.chdir(backend_dir)

from dotenv import load_dotenv
load_dotenv(backend_dir / ".env")

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver

from app.agent.graph import get_graph_with_checkpointer


async def main():
    prompt = sys.argv[1] if len(sys.argv) > 1 else "Donne-moi la liste des clients"
    config = {"configurable": {"thread_id": "cli-test-list-clients"}}
    memory = MemorySaver()
    graph = get_graph_with_checkpointer(memory)

    print(f"User: {prompt}\n")
    result = await graph.ainvoke({"messages": [HumanMessage(content=prompt)]}, config=config)

    # If interrupted before tools, resume once for this test
    state = graph.get_state(config)
    if state.next == ("tools",):
        print("[CLI] Interruption (tools) - resuming...\n")
        result = await graph.ainvoke(None, config=config)

    for msg in result.get("messages", []):
        role = getattr(msg, "type", type(msg).__name__)
        content = getattr(msg, "content", str(msg))
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            print(f"Tool calls: {[tc.get('name') for tc in msg.tool_calls]}")
            for tc in msg.tool_calls:
                print(f"  -> {tc.get('name')}({tc.get('args')})")
        if content:
            print(f"{role}: {content[:500]}{'...' if len(str(content)) > 500 else ''}\n")


if __name__ == "__main__":
    asyncio.run(main())
