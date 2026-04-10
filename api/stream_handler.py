"""
📡 Socket.IO stream handler for game session responses.

Processes LangGraph stream output and emits Socket.IO events
(stream_start, stream_token, stream_end) with character/narrator attribution.
"""
from logging import getLogger
from uuid import uuid4

import socketio
from langchain_core.messages import AIMessageChunk, ToolMessageChunk

from agents.dungeon_master import NARRATOR_NAME


logger = getLogger(__name__)

NODE_PLANNER = "planner"
NODE_USE_TOOLS = "use_tools"
NODE_NARRATOR = "npc_narrator"
NODE_DM_NARRATOR_OPENING = "dm_narrator_opening"
NODE_DM_NARRATOR_CLOSING = "dm_narrator_closing"

STREAMABLE_NODES = frozenset({
    NODE_DM_NARRATOR_OPENING,
    NODE_DM_NARRATOR_CLOSING,
})

DM_NARRATOR_NODES = frozenset({NODE_DM_NARRATOR_OPENING, NODE_DM_NARRATOR_CLOSING})

SKIP_NODES = frozenset({NODE_PLANNER, NODE_USE_TOOLS})


def resolve_speaker(character_list: list[str], path: list[str], langgraph_node: str) -> str:
    """Resolve speaker name from stream metadata.

    DM narrator nodes always return the Narrator name.
    For NPC nodes, the innermost path element matching a character wins.
    """
    if langgraph_node in DM_NARRATOR_NODES:
        return NARRATOR_NAME

    if len(character_list) == 1:
        return character_list[0]

    matching = [c for c in path if c in character_list]
    if matching:
        return matching[-1]
    return NARRATOR_NAME


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
        self._current_node: str | None = None
        self._prefix_buffer: str = ""
        self._prefix_stripped: bool = False
        self.message_ids: list[str] = []

    async def _start_new_message(self, speaker: str) -> None:
        if self._current_message_id:
            await self.sio.emit(
                "stream_end",
                {"messageId": self._current_message_id},
                to=self.sid,
            )

        self._current_message_id = str(uuid4())
        self._current_speaker = speaker
        self._prefix_buffer = ""
        self._prefix_stripped = False
        self.message_ids.append(self._current_message_id)
        await self.sio.emit(
            "stream_start",
            {"messageId": self._current_message_id, "name": speaker},
            to=self.sid,
        )
        logger.debug("🎬 stream_start: speaker=%s, id=%s", speaker, self._current_message_id)

    async def _emit_stripped_token(self, content: str, speaker: str) -> None:
        """Buffer initial tokens to strip the `Name: ` prefix, then forward the rest."""
        if self._prefix_stripped:
            await self.sio.emit(
                "stream_token",
                {"messageId": self._current_message_id, "token": content},
                to=self.sid,
            )
            return

        self._prefix_buffer += content
        expected = f"{speaker}: "

        if len(self._prefix_buffer) >= len(expected):
            if self._prefix_buffer.startswith(expected):
                remainder = self._prefix_buffer[len(expected):]
                self._prefix_stripped = True
                if remainder:
                    await self.sio.emit(
                        "stream_token",
                        {"messageId": self._current_message_id, "token": remainder},
                        to=self.sid,
                    )
            else:
                self._prefix_stripped = True
                await self.sio.emit(
                    "stream_token",
                    {"messageId": self._current_message_id, "token": self._prefix_buffer},
                    to=self.sid,
                )
        elif not expected.startswith(self._prefix_buffer):
            self._prefix_stripped = True
            await self.sio.emit(
                "stream_token",
                {"messageId": self._current_message_id, "token": self._prefix_buffer},
                to=self.sid,
            )

    async def _handle_ai_chunk(
        self, msg: AIMessageChunk, ns_path: list[str], langgraph_node: str
    ) -> None:
        if langgraph_node in SKIP_NODES:
            logger.debug("🧠 %s chunk (internal, not streamed)", langgraph_node)
            return

        if langgraph_node not in STREAMABLE_NODES:
            return

        speaker = resolve_speaker(self.character_list, ns_path, langgraph_node)
        skip_prefix = langgraph_node in DM_NARRATOR_NODES

        if speaker != self._current_speaker or langgraph_node != self._current_node:
            await self._start_new_message(speaker)
            self._current_node = langgraph_node
            if skip_prefix:
                self._prefix_stripped = True

        if msg.content and self._current_message_id:
            await self._emit_stripped_token(msg.content, speaker)

    async def _handle_tool_chunk(self, msg: ToolMessageChunk, ns_path: list[str]) -> None:
        logger.debug("🔧 Tool chunk: %s", msg.content[:80] if msg.content else "")

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
