"""
📡 Socket.IO stream handler for NPC assistant responses.

Processes LangGraph stream output and emits Socket.IO events
(stream_start, stream_token, stream_end) with character attribution.
"""
from logging import getLogger
from uuid import uuid4

import socketio
from langchain_core.messages import AIMessageChunk, ToolMessageChunk


logger = getLogger(__name__)

NODE_PLANNER = "planner"
NODE_USE_TOOLS = "use_tools"
NODE_NARRATOR = "npc_narrator"
NARRATOR_NODES = frozenset({NODE_PLANNER, NODE_USE_TOOLS, NODE_NARRATOR})

def resolve_speaker(character_list: list[str], path: list[str]) -> str:
    """Resolve character name from stream metadata. Innermost path element wins."""
    if len(character_list) == 1:
        return character_list[0]
    
    matching = [c for c in path if c in character_list]
    return matching[-1]


def path_from_namespace(namespace: tuple[str, ...]) -> list[str]:
    """Extract node names from namespace, e.g. ('character_1:uuid', 'planner:uuid') -> ['character_1', 'planner']."""
    return [
        name for part in namespace
        if not (name := part.split(":")[0] if ":" in part else part).startswith("__")
    ]


class SocketStreamHandler:
    """Processes a LangGraph astream and emits Socket.IO events per character speaker."""

    def __init__(
        self,
        sio: socketio.AsyncServer,
        sid: str,
        character_list: list[str],
    ):
        self.sio = sio
        self.sid = sid
        self.character_list = character_list
        self._current_message_id: str | None = None
        self._current_speaker: str | None = None

    async def _start_new_message(self, speaker: str) -> None:
        if self._current_message_id:
            await self.sio.emit(
                "stream_end",
                {"messageId": self._current_message_id},
                to=self.sid,
            )

        self._current_message_id = str(uuid4())
        self._current_speaker = speaker
        await self.sio.emit(
            "stream_start",
            {"messageId": self._current_message_id, "name": speaker},
            to=self.sid,
        )
        logger.debug("🎬 stream_start: speaker=%s, id=%s", speaker, self._current_message_id)

    async def _handle_ai_chunk(
        self, msg: AIMessageChunk, ns_path: list[str], langgraph_node: str
    ) -> None:
        speaker = resolve_speaker(self.character_list, ns_path)

        if langgraph_node == NODE_NARRATOR:
            if speaker != self._current_speaker:
                await self._start_new_message(speaker)

            if msg.content and self._current_message_id:
                await self.sio.emit(
                    "stream_token",
                    {"messageId": self._current_message_id, "token": msg.content},
                    to=self.sid,
                )
        elif langgraph_node == NODE_PLANNER:
            logger.debug("🧠 Planner chunk from %s (skipping for now)", speaker)

    async def _handle_tool_chunk(self, msg: ToolMessageChunk, ns_path: list[str]) -> None:
        speaker = resolve_speaker(self.character_list, ns_path)
        logger.debug("🔧 Tool chunk from %s: %s", speaker, msg.content[:80] if msg.content else "")

    async def process(self, stream: object) -> None:
        """Iterate the LangGraph stream and emit Socket.IO events."""
        try:
            async for item in stream:
                namespace, (msg, metadata) = item
                ns_path = path_from_namespace(namespace)
                langgraph_node = metadata["langgraph_node"]

                if isinstance(msg, AIMessageChunk):
                    await self._handle_ai_chunk(msg, ns_path, langgraph_node)
                elif isinstance(msg, ToolMessageChunk):
                    await self._handle_tool_chunk(msg, ns_path)
                else:
                    logger.debug("📦 Unhandled message type: %s", type(msg).__name__)
        except Exception:
            logger.exception("💥 Error processing stream for sid=%s", self.sid)
            await self.sio.emit(
                "error",
                {"message": "An error occurred while processing the response."},
                to=self.sid,
            )
        finally:
            if self._current_message_id:
                await self.sio.emit(
                    "stream_end",
                    {"messageId": self._current_message_id},
                    to=self.sid,
                )
                logger.debug("🏁 stream_end: id=%s", self._current_message_id)
