"""
🧩 Assistant function for streaming NPC responses with final_answer, planner_step, and tool_step.
"""
from logging import getLogger

import chainlit as cl
from langchain_core.messages import AIMessageChunk, ToolMessageChunk

logger = getLogger(__name__)

# Node names from nonplayer graph
NODE_PLANNER = "planner"
NODE_USE_TOOLS = "use_tools"
NODE_NARRATOR = "npc_narrator"


def _effective_node(metadata: dict) -> str | None:
    """Resolve node name from metadata (supports nested graphs via langgraph_path)."""
    path = metadata.get("langgraph_path")
    if path:
        return path[-1] if path else None
    return metadata.get("langgraph_node")


async def stream_npc_assistant(
    _name: str,
    stream,
) -> None:
    """
    Stream NPC response with final_answer (author=_name), planner_step, and tool_step.
    """
    final_answer = cl.Message(content="", author=_name)
    planner_step = cl.Step(name="🧠 Thinking", type="tool")
    tool_step = cl.Step(name="🔧 Using Tools", type="tool")

    for msg, metadata in stream:
        node_name = _effective_node(metadata)

        if isinstance(msg, AIMessageChunk):
            if node_name == NODE_NARRATOR:
                await final_answer.stream_token(msg.content)
            elif node_name == NODE_PLANNER:
                async with planner_step as step:
                    await step.stream_token(msg.content)
            else:
                logger.debug(f"📝 AIMessageChunk from node {node_name}, skipping")

        elif isinstance(msg, ToolMessageChunk):
            async with tool_step as step:
                await step.stream_token(msg.content)

        else:
            logger.warning(f"🚨 Unknown message type: {type(msg)} from node: {node_name}")

    await final_answer.send()
