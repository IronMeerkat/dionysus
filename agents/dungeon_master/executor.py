"""Run the DM-selected NPC agents in order, streaming their turns to the client."""
from logging import getLogger
from uuid import uuid4

from langchain_core.messages import AIMessageChunk, AnyMessage

from agents.dungeon_master.context import DMContext
from agents.dungeon_master.schemas import DungeonMasterState
from agents.nonplayer import spawn_npc_directed
from hephaestus.agent_architectures.retry import FailedToSelfCorrect
from contracts.turn_events import TurnSink, strip_speaker_prefix

logger = getLogger(__name__)

NODE_NARRATOR = "npc_narrator"


async def _stream_npc(
    npc_graph: object,
    input_messages: list[AnyMessage],
    lore: str,
    query_vector: list[float] | None,
    speaker: str,
    sink: TurnSink,
) -> list[AnyMessage]:
    """Stream an NPC graph, narrating its tokens into ``sink``.

    Tokens are forwarded live for responsiveness, but the *authoritative* message is
    the cleaned one the npc_narrator node returns (prefix-stripping, foreign-turn
    truncation, retries) -- raw chunks may contain several retry attempts concatenated.
    ``stream_end`` carries the cleaned content so the frontend can snap the live
    bubble to it (or drop the bubble when narration failed entirely).

    Returns the cleaned delta messages, carrying the streamed bubble id.
    """
    message_id: str | None = None
    prefix_buffer = ""
    prefix_stripped = False
    final_messages: list[AnyMessage] = []
    expected = f"{speaker}: "

    async def ensure_started() -> None:
        nonlocal message_id
        if message_id is None:
            message_id = str(uuid4())
            await sink.stream_start(message_id, speaker)

    stream = npc_graph.astream(
        {"messages": input_messages, "lore": lore, "query_vector": query_vector},
        stream_mode=["messages", "updates"], subgraphs=True,
    )

    async for _namespace, mode, payload in stream:
        if mode == "updates":
            for node_name, update in payload.items():
                if node_name == NODE_NARRATOR and update:
                    final_messages = list(update.get("messages") or [])
            continue

        msg, metadata = payload
        if (
            not isinstance(msg, AIMessageChunk)
            or metadata.get("langgraph_node", "") != NODE_NARRATOR
            or not msg.content
        ):
            continue

        await ensure_started()
        if prefix_stripped:
            await sink.stream_token(message_id, msg.content)
            continue

        # Buffer until the leading "{speaker}: " prefix is either stripped or ruled out.
        prefix_buffer += msg.content
        if len(prefix_buffer) >= len(expected) or not expected.startswith(prefix_buffer):
            prefix_stripped = True
            flush = prefix_buffer[len(expected):] if prefix_buffer.startswith(expected) else prefix_buffer
            if flush:
                await sink.stream_token(message_id, flush)

    if not final_messages:
        if message_id is not None:
            # Narration failed after retries: retract the live bubble. The empty
            # string is load-bearing -- it tells the client to DROP the bubble,
            # where omitting content would tell it to keep the partial text.
            logger.warning(f"🗑️ {speaker}: no usable narration, retracting streamed bubble {message_id}")
            await sink.stream_end(message_id, "")
        return []

    final_msg = final_messages[-1]
    display_content = strip_speaker_prefix(final_msg.content, speaker)

    await ensure_started()
    # Reuse the bubble id so the persisted DB row and the frontend agree.
    final_msg.id = message_id
    await sink.stream_end(message_id, display_content)
    return final_messages


def make_npc_executor(ctx: DMContext):
    async def npc_executor(state: DungeonMasterState) -> dict:
        """Dynamically build and run each selected NPC in the DM's order."""
        plan = state.plan
        if not plan or not plan.responding_npcs:
            return {"messages": []}

        all_messages: list[AnyMessage] = []
        for directive in plan.responding_npcs:
            character = next((c for c in ctx.conversation.characters if c.name == directive.name), None)
            if character is None:
                logger.warning(f"⚠️ NPC '{directive.name}' not found in conversation characters")
                continue

            npc_graph = spawn_npc_directed(character, ctx.conversation, directive, state.query_vector)
            input_messages = [*state.messages, *all_messages]
            try:
                # One path, client attached or not: a headless run narrates into
                # a null sink. The old no-socket branch called ainvoke and sliced
                # raw state instead, so it produced different message content
                # than live play for the same input.
                delta = await _stream_npc(
                    npc_graph, input_messages, state.lore, state.query_vector,
                    character.name, ctx.sink,
                )
                all_messages.extend(delta)
                logger.info(f"🎭 {directive.name} produced {len(delta)} message(s)")
            except FailedToSelfCorrect as exc:
                logger.exception(f"🔁 {directive.name} failed to self-correct")
                await ctx.sink.error(str(exc))  # stream only; never appended to messages
            except Exception:
                logger.exception(f"💥 NPC graph failed for '{directive.name}'")

        return {"messages": all_messages}

    return npc_executor
