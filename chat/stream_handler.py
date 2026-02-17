"""
📡 Stream handler for NPC assistant responses.

Processes LangGraph stream output and renders to Chainlit (final_answer, planner_step, tool_step).
"""
from logging import getLogger

import chainlit as cl
from langchain_core.messages import AIMessageChunk, AIMessage, HumanMessage, ToolMessageChunk, ToolMessage

from metadata import NODE_NARRATOR, NODE_PLANNER, effective_node, path_from_namespace, resolve_speaker

logger = getLogger(__name__)


class NPCStreamHandler:
    """Handles streaming NPC responses with character attribution and step rendering."""

    def __init__(self, graph_node_to_character_name: dict[str, str]):
        self.mapping = graph_node_to_character_name or {}
        self.planner_steps: dict[str, cl.Step] = {}
        self.tool_steps: dict[str, cl.Step] = {}
        self.current_answer: cl.Message = cl.Message(content="")

    def _step_for_speaker(self, steps: dict[str, cl.Step], label: str, speaker: str) -> cl.Step:
        if speaker not in steps:
            steps[speaker] = cl.Step(name=f"{label} ({speaker})", type="tool")
        return steps[speaker]

    async def _handle_ai_message(
        self, msg: AIMessageChunk | AIMessage, metadata: dict, path_from_ns: list[str] | None
    ) -> None:
        speaker = resolve_speaker(metadata, self.mapping, path_from_ns)
        if self.current_answer.author != speaker:
            self.current_answer = cl.Message(content=f"{speaker}:", author=speaker)
        node_name = effective_node(metadata, path_from_ns)
        is_narrator = node_name == NODE_NARRATOR or (node_name and node_name in self.mapping)

        if is_narrator:
            self.current_answer.author = speaker
            await self.current_answer.stream_token(msg.content)
        elif node_name == NODE_PLANNER:
            speaker = resolve_speaker(metadata, self.mapping, path_from_ns)
            step = self._step_for_speaker(self.planner_steps, "🧠 Thinking", speaker)
            async with step as s:
                await s.stream_token(msg.content)
        else:
            logger.debug(f"📝 AIMessageChunk from node {node_name}, skipping")

    async def _handle_tool_message(
        self, msg: ToolMessageChunk | ToolMessage, metadata: dict, path_from_ns: list[str] | None
    ) -> None:
        speaker = resolve_speaker(metadata, self.mapping, path_from_ns)
        step = self._step_for_speaker(self.tool_steps, "🔧 Using Tools", speaker)
        async with step as s:
            await s.stream_token(msg.content)

    async def process(self, stream: object) -> None:
        """Process stream items and render to Chainlit."""
        for item in stream:
            if isinstance(item, tuple) and len(item) == 2:
                namespace, payload = item
                msg, metadata = payload
                path_from_ns = path_from_namespace(namespace) if isinstance(namespace, tuple) else None
            else:
                logger.warning(f"❓ Non-tuple stream item: {item}")
                msg, metadata = item
                path_from_ns = None

            if isinstance(msg, (AIMessageChunk, AIMessage)):
                await self._handle_ai_message(msg, metadata, path_from_ns)
            elif isinstance(msg, (ToolMessageChunk, ToolMessage)):
                await self._handle_tool_message(msg, metadata, path_from_ns)
            elif isinstance(msg, HumanMessage):
                pass  # User input already shown by Chainlit
            else:
                logger.warning(f"🚨 Unknown message type: {type(msg)} from node: {effective_node(metadata, path_from_ns)}")

        if self.current_answer is not None:
            await self.current_answer.send()
