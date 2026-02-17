"""
🧩 Assistant entry point for streaming NPC responses with final_answer, planner_step, and tool_step.
"""
import chainlit as cl

from stream_handler import NPCStreamHandler


async def stream_npc_assistant(
    _name: str,
    stream,
    *,
    subgraphs: bool = False,
) -> None:
    """
    Stream NPC response with final_answer (author=resolved character), planner_step, and tool_step.
    Narrator output is attributed to the correct character via graph_node_to_character_name.
    When subgraphs=True, stream yields (namespace, (msg, metadata)); else (msg, metadata).
    """
    mapping = cl.user_session.get("graph_node_to_character_name") or {}
    handler = NPCStreamHandler(mapping)
    await handler.process(stream, subgraphs)
