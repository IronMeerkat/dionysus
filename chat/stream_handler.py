"""
📡 Stream handler for NPC assistant responses.

Processes LangGraph stream output and renders to Chainlit (final_answer, planner_step, tool_step).
"""
from logging import getLogger

import chainlit as cl
from langchain_core.messages import AIMessageChunk, AIMessage, ToolMessageChunk, ToolMessage

from metadata import NODE_NARRATOR, NODE_PLANNER, path_from_namespace, resolve_speaker

logger = getLogger(__name__)


class NPCStreamHandler:
    """Handles streaming NPC responses with character attribution and step rendering."""

    def __init__(self, character_list: list[str]):
        self.character_list = character_list
        self.planner_steps: dict[str, cl.Step] = {}
        self.tool_steps: dict[str, cl.Step] = {}
        self.current_answer: cl.Message = cl.Message(content="")

    def _step_for_speaker(self, steps: dict[str, cl.Step], label: str, speaker: str) -> cl.Step:
        if speaker not in steps:
            steps[speaker] = cl.Step(name=f"{label} ({speaker})", type="tool")
        return steps[speaker]

    async def _handle_ai_message(self, msg: AIMessageChunk, ns_path: list[str], langgraph_node: str) -> None:

        speaker = resolve_speaker(self.character_list, ns_path)
        if self.current_answer.author != speaker:
            self.current_answer = cl.Message(content="", author=speaker)

        if langgraph_node == NODE_NARRATOR:
            await self.current_answer.stream_token(msg.content)
        elif langgraph_node == NODE_PLANNER:
            step = self._step_for_speaker(self.planner_steps, "🧠 Thinking", speaker)
            async with step as s:
                await s.stream_token(msg.content)
        else:
            logger.debug(f"📝 AIMessageChunk from node {langgraph_node}, skipping")

    async def _handle_tool_message(self, msg: ToolMessageChunk, ns_path: list[str]) -> None:
        speaker = resolve_speaker(self.character_list, ns_path)
        step = self._step_for_speaker(self.tool_steps, "🔧 Using Tools", speaker)
        async with step as s:
            await s.stream_token(msg.content)

    async def process(self, stream: object) -> None:
        """Process stream items and render to Chainlit."""
        async for item in stream:
            namespace, (msg, metadata) = item
            ns_path = path_from_namespace(namespace)
            langgraph_node = metadata["langgraph_node"]

            if isinstance(msg, AIMessageChunk):
                await self._handle_ai_message(msg, ns_path, langgraph_node)
            elif isinstance(msg, ToolMessageChunk):
                await self._handle_tool_message(msg, ns_path)
            else:
                logger.debug(f"Unhandled message type: {type(msg)}")

        if self.current_answer is not None:
            await self.current_answer.send()
