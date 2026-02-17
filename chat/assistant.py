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


def _resolve_speaker(
    metadata: dict,
    graph_node_to_character_name: dict[str, str],
) -> str | None:
    """
    Resolve character name from stream metadata using graph_node_to_character_name.
    For nested graphs: path[0] is the parent node (e.g. character_1).
    For single-agent: path may be [NODE_NARRATOR], mapped explicitly.
    """
    path = metadata.get("langgraph_path")
    if path:
        # Try parent node first (multi-agent: character_1, character_2, ...)
        if len(path) >= 2:
            parent = path[0]
            if parent in graph_node_to_character_name:
                return graph_node_to_character_name[parent]
        # Single-agent or direct: path[-1] may be npc_narrator
        leaf = path[-1] if path else None
        if leaf and leaf in graph_node_to_character_name:
            return graph_node_to_character_name[leaf]
    node = metadata.get("langgraph_node")
    if node and node in graph_node_to_character_name:
        return graph_node_to_character_name[node]
    return None


async def stream_npc_assistant(
    _name: str,
    stream,
) -> None:
    """
    Stream NPC response with final_answer (author=resolved character), planner_step, and tool_step.
    Narrator output is attributed to the correct character via graph_node_to_character_name.
    """
    mapping = cl.user_session.get("graph_node_to_character_name") or {}
    planner_step = cl.Step(name="🧠 Thinking", type="tool")
    tool_step = cl.Step(name="🔧 Using Tools", type="tool")
    current_answer: cl.Message | None = None
    current_author: str | None = None

    for msg, metadata in stream:
        node_name = _effective_node(metadata)

        if isinstance(msg, AIMessageChunk):
            if node_name == NODE_NARRATOR:
                speaker = _resolve_speaker(metadata, mapping)
                if speaker is None:
                    logger.error(
                        f"❌ Cannot resolve speaker for narrator output: "
                        f"metadata={metadata}, mapping={list(mapping.keys())}"
                    )
                    await cl.Message(
                        content="❌ Could not determine which character is speaking. Please try again."
                    ).send()
                    return
                if current_answer is None or current_author != speaker:
                    if current_answer is not None:
                        await current_answer.send()
                    current_answer = cl.Message(content="", author=speaker)
                    current_author = speaker
                await current_answer.stream_token(msg.content)
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

    if current_answer is not None:
        await current_answer.send()
