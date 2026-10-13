"""📡 Drives a DM turn's LangGraph stream into a ``TurnSink``."""
from logging import getLogger
from uuid import uuid4

from langchain_core.messages import AIMessage, AIMessageChunk, SystemMessage

from agents.dungeon_master.schemas import NARRATOR_NAME, STREAM_MESSAGE_ID_KEY, STREAM_SPEAKER_KEY
from contracts.turn_events import TurnSink, strip_speaker_prefix

logger = getLogger(__name__)

NODE_DM_NARRATOR_OPENING = "dm_narrator_opening"
NODE_DM_NARRATOR_CLOSING = "dm_narrator_closing"
NODE_OOC_RESPONDER = "ooc_responder"
NODE_NPC_NARRATOR = "npc_narrator"
NODE_VALIDATOR = "validator_node"

STREAMABLE_NODES = frozenset({
    NODE_DM_NARRATOR_OPENING,
    NODE_DM_NARRATOR_CLOSING,
    NODE_OOC_RESPONDER,
    NODE_NPC_NARRATOR,
})


class TurnStreamPump:
    """Consumes a turn's message stream and narrates it into a ``TurnSink``."""

    def __init__(self, sink: TurnSink) -> None:
        self._sink = sink
        self._open_id: str | None = None
        self._last_id: str | None = None

    async def _open_bubble(self, message_id: str, speaker: str = NARRATOR_NAME) -> None:
        if self._open_id == message_id:
            return
        await self._close_bubble()
        self._open_id = message_id
        self._last_id = message_id
        await self._sink.stream_start(message_id, speaker)
        logger.debug(f"🎬 stream_start: speaker={speaker}, id={message_id}")

    async def _close_bubble(self, content: str | None = None) -> None:
        if self._open_id is None:
            return
        await self._sink.stream_end(self._open_id, content)
        logger.debug(f"🏁 stream_end: id={self._open_id}")
        self._open_id = None

    async def _handle_chunk(self, msg: AIMessageChunk, metadata: dict) -> None:
        message_id = metadata.get(STREAM_MESSAGE_ID_KEY)
        speaker = metadata.get(STREAM_SPEAKER_KEY) or NARRATOR_NAME
        if message_id is None:
            message_id = str(uuid4())
            logger.error(
                f"🪪 Streaming node emitted tokens without '{STREAM_MESSAGE_ID_KEY}' "
                f"metadata; bubble {message_id} will not match its persisted row"
            )
        await self._open_bubble(message_id, speaker)
        if msg.content:
            await self._sink.stream_token(message_id, str(msg.content))

    async def _handle_message(self, msg: AIMessage, metadata: dict) -> None:
        message_id = msg.id
        if message_id is None:
            logger.error("🪪 Streamable node returned a message with no id; cannot stream it")
            return
        speaker = msg.name or metadata.get(STREAM_SPEAKER_KEY) or NARRATOR_NAME
        content = strip_speaker_prefix(str(msg.content), speaker)
        streamed_live = self._open_id == message_id
        await self._open_bubble(message_id, speaker)
        if not streamed_live:
            await self._sink.stream_token(message_id, content)
        await self._close_bubble(content)

    async def process(self, stream: object) -> None:
        try:
            async for item in stream:
                _namespace, (msg, metadata) = item
                node = metadata["langgraph_node"]
                if node == NODE_VALIDATOR and isinstance(msg, SystemMessage) and self._last_id:
                    await self._close_bubble()
                    await self._sink.stream_end(self._last_id, "")
                    self._last_id = None
                    continue
                if node not in STREAMABLE_NODES:
                    continue
                if isinstance(msg, AIMessageChunk):
                    await self._handle_chunk(msg, metadata)
                elif isinstance(msg, AIMessage):
                    await self._handle_message(msg, metadata)
                else:
                    logger.debug(f"📦 Unhandled message type: {type(msg).__name__}")
        except Exception:
            logger.exception("💥 Error processing turn stream")
            await self._sink.error("An error occurred while processing the response.")
        finally:
            await self._close_bubble()
