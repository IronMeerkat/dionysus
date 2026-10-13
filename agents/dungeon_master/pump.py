"""📡 Drives a DM turn's LangGraph stream into a ``TurnSink``.

This lives with the engine, not the gateway: it has to know which graph nodes
speak to the player, and node names are the graph's private business. The
gateway only supplies a sink.

Which nodes stream, and which do not:

- ``dm_narrator_opening`` / ``dm_narrator_closing`` / ``ooc_responder`` are the
  DM's own voice and stream through here.
- ``npc_narrator`` does NOT. The NPC executor streams its own bubbles (it needs
  the cleaned, retry-collapsed text, which raw chunks do not give it), so
  emitting it here as well would double every NPC line. Same for the dice line,
  which ``roll_announcer`` emits directly.
- Everything else (planner, classifiers, tool loops) is internal reasoning and
  never reaches the player.

Because every streaming node is a DM-voice node, the speaker is always the
Narrator. The previous implementation carried a ``character_list`` plus
namespace-path speaker resolution and a "{speaker}: " prefix stripper; all of
it was unreachable for exactly that reason.

Two kinds of event arrive from a streamable node, and BOTH matter:

1. ``AIMessageChunk`` -- live tokens from a model call. Their own id is the
   LangChain run id, so the bubble is keyed on ``STREAM_MESSAGE_ID_KEY`` from
   the run metadata, which the node minted before calling the model.
2. ``AIMessage`` -- the node's state update, carrying the authoritative content
   and the id the message is persisted under. Nodes that narrate WITHOUT a
   model call (``narration._direct``, which is every closing narration and any
   single-beat opening) emit only this, so ignoring it left that narration
   invisible to the player until a page reload.

Keying both on the same node-minted id is what lets the streamed bubble and the
persisted row agree, and is why no client-side id remap is needed.
"""
from logging import getLogger
from uuid import uuid4

from langchain_core.messages import AIMessage, AIMessageChunk

from agents.dungeon_master.schemas import NARRATOR_NAME, STREAM_MESSAGE_ID_KEY
from contracts.turn_events import TurnSink, strip_speaker_prefix

logger = getLogger(__name__)

NODE_DM_NARRATOR_OPENING = "dm_narrator_opening"
NODE_DM_NARRATOR_CLOSING = "dm_narrator_closing"
NODE_OOC_RESPONDER = "ooc_responder"

# Nodes whose output is the DM speaking to the player.
STREAMABLE_NODES = frozenset({
    NODE_DM_NARRATOR_OPENING,
    NODE_DM_NARRATOR_CLOSING,
    NODE_OOC_RESPONDER,
})


class TurnStreamPump:
    """Consumes a turn's message stream and narrates it into a ``TurnSink``."""

    def __init__(self, sink: TurnSink) -> None:
        self._sink = sink
        self._open_id: str | None = None

    async def _open_bubble(self, message_id: str) -> None:
        if self._open_id == message_id:
            return
        await self._close_bubble()
        self._open_id = message_id
        await self._sink.stream_start(message_id, NARRATOR_NAME)
        logger.debug(f"🎬 stream_start: speaker={NARRATOR_NAME}, id={message_id}")

    async def _close_bubble(self, content: str | None = None) -> None:
        if self._open_id is None:
            return
        await self._sink.stream_end(self._open_id, content)
        logger.debug(f"🏁 stream_end: id={self._open_id}")
        self._open_id = None

    async def _handle_chunk(self, msg: AIMessageChunk, metadata: dict) -> None:
        """Live tokens: stream them under the node's pre-minted message id."""
        message_id = metadata.get(STREAM_MESSAGE_ID_KEY)
        if message_id is None:
            # Fail-secure: rather than drop the narration, stream it under a
            # provisional id -- but say so loudly, because the client's bubble
            # id will NOT match the persisted row and editing it will 404.
            message_id = str(uuid4())
            logger.error(
                f"🪪 Streaming node emitted tokens without '{STREAM_MESSAGE_ID_KEY}' "
                f"metadata; bubble {message_id} will not match its persisted row"
            )
        await self._open_bubble(message_id)
        if msg.content:
            await self._sink.stream_token(message_id, str(msg.content))

    async def _handle_message(self, msg: AIMessage) -> None:
        """The node's state update: authoritative id and content.

        Closes the live bubble with the cleaned text (collapsing any retry
        attempts the raw tokens contained). When nothing streamed -- an
        LLM-free ``_direct`` narration -- the whole bubble is emitted here.
        """
        message_id = msg.id
        if message_id is None:
            logger.error("🪪 Streamable node returned a message with no id; cannot stream it")
            return

        content = strip_speaker_prefix(str(msg.content), NARRATOR_NAME)
        streamed_live = self._open_id == message_id
        await self._open_bubble(message_id)
        if not streamed_live:
            # Nothing streamed for this message, so the client has no text yet.
            await self._sink.stream_token(message_id, content)
        await self._close_bubble(content)

    async def process(self, stream: object) -> None:
        """Iterate the LangGraph stream, narrating it into the sink.

        Fail-secure boundary: a stream failure is logged and reported to the
        client, and any open bubble is closed WITHOUT a content override so the
        partial text the player already saw survives. The turn degrades; the
        socket handler does not crash.
        """
        try:
            async for item in stream:
                _namespace, (msg, metadata) = item
                if metadata["langgraph_node"] not in STREAMABLE_NODES:
                    continue
                # AIMessageChunk subclasses AIMessage, so check it first.
                if isinstance(msg, AIMessageChunk):
                    await self._handle_chunk(msg, metadata)
                elif isinstance(msg, AIMessage):
                    await self._handle_message(msg)
                else:
                    logger.debug(f"📦 Unhandled message type: {type(msg).__name__}")
        except Exception:
            logger.exception("💥 Error processing turn stream")
            await self._sink.error("An error occurred while processing the response.")
        finally:
            await self._close_bubble()
