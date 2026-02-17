"""
🧩 Assistant function for streaming NPC responses with final_answer, planner_step, and tool_step.
"""
from logging import getLogger

import chainlit as cl
from langchain_core.messages import AIMessageChunk, AIMessage, HumanMessage, ToolMessageChunk, ToolMessage

logger = getLogger(__name__)

# Node names from nonplayer graph
NODE_PLANNER = "planner"
NODE_USE_TOOLS = "use_tools"
NODE_NARRATOR = "npc_narrator"


def _effective_node(metadata: dict, path_from_namespace: list[str] | None = None) -> str | None:
    """
    Resolve node name from metadata (supports nested graphs via langgraph_path).
    When subgraphs=True, namespace may only have parent (e.g. character_1); the inner
    node (planner, use_tools, npc_narrator) comes from metadata.langgraph_node.
    """
    inner_node = metadata.get("langgraph_node")
    path = path_from_namespace or metadata.get("langgraph_path")
    # Prefer inner node from metadata when present (planner, use_tools, npc_narrator)
    if inner_node and inner_node in (NODE_PLANNER, NODE_USE_TOOLS, NODE_NARRATOR):
        return inner_node
    if path:
        return path[-1] if path else None
    return inner_node


def _resolve_speaker(
    metadata: dict,
    graph_node_to_character_name: dict[str, str],
    path_from_namespace: list[str] | None = None,
) -> str | None:
    """
    Resolve character name from stream metadata using graph_node_to_character_name.
    For multi-agent swarm: path may be ["character_1", "npc_narrator"] from namespace.
    Use the LAST matching element so we get the innermost/current character node
    (e.g. character_2 over character_1 when both appear in path).
    """
    path = path_from_namespace or metadata.get("langgraph_path")
    if path:
        # Find last path element that maps to a character (innermost node wins)
        matching = [graph_node_to_character_name[e] for e in path if e in graph_node_to_character_name]
        if matching:
            return matching[-1]
    node = metadata.get("langgraph_node")
    if node and node in graph_node_to_character_name:
        return graph_node_to_character_name[node]
    raise ValueError("Could not determine which character is speaking. Please try again.", metadata, graph_node_to_character_name, path_from_namespace)


def _path_from_namespace(namespace: tuple[str, ...]) -> list[str]:
    """Extract node names from namespace, e.g. ('character_1:uuid', 'planner:uuid') -> ['character_1', 'planner']."""
    result = []
    for part in namespace:
        name = part.split(":")[0] if ":" in part else part
        if not name.startswith("__"):  # skip internal nodes like __pregel_pull
            result.append(name)
    return result


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
    planner_steps: dict[str, cl.Step] = {}
    tool_steps: dict[str, cl.Step] = {}
    current_answer: cl.Message = cl.Message(content="")

    def _step_for_speaker(steps: dict[str, cl.Step], label: str, speaker: str) -> cl.Step:
        if speaker not in steps:
            steps[speaker] = cl.Step(name=f"{label} ({speaker})", type="tool")
        return steps[speaker]

    for item in stream:
        if subgraphs and isinstance(item, tuple) and len(item) == 2:
            namespace, payload = item
            msg, metadata = payload
            path_from_ns = _path_from_namespace(namespace) if isinstance(namespace, tuple) else None
        else:
            msg, metadata = item
            path_from_ns = None

        node_name = _effective_node(metadata, path_from_ns)

        if isinstance(msg, (AIMessageChunk, AIMessage)):
            speaker = _resolve_speaker(metadata, mapping, path_from_ns)
            if current_answer.author != speaker:
                current_answer = cl.Message(content="", author=speaker)
            is_narrator = node_name == NODE_NARRATOR or (
                node_name and node_name in mapping
            )

            if is_narrator:
                current_answer.author = speaker
                await current_answer.stream_token(msg.content)
            elif node_name == NODE_PLANNER:
                speaker = _resolve_speaker(metadata, mapping, path_from_ns) or "Unknown"
                step = _step_for_speaker(planner_steps, "🧠 Thinking", speaker)
                async with step as s:
                    await s.stream_token(msg.content)
            else:
                logger.debug(f"📝 AIMessageChunk from node {node_name}, skipping")

        elif isinstance(msg, (ToolMessageChunk, ToolMessage)):
            speaker = _resolve_speaker(metadata, mapping, path_from_ns) or "Unknown"
            step = _step_for_speaker(tool_steps, "🔧 Using Tools", speaker)
            async with step as s:
                await s.stream_token(msg.content)

        elif isinstance(msg, HumanMessage):
            # User input forwarded through graph; already shown by Chainlit, skip
            pass

        else:
            logger.warning(f"🚨 Unknown message type: {type(msg)} from node: {node_name}")

    if current_answer is not None:
        await current_answer.send()
