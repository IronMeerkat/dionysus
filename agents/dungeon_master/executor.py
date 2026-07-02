"""Run the DM-selected NPC agents in order, streaming their turns to the client."""
from logging import getLogger
from uuid import uuid4

import socketio
from langchain_core.messages import AIMessageChunk, AnyMessage

from agents.dungeon_master.context import DMContext
from agents.dungeon_master.schemas import DungeonMasterState
from agents.nonplayer import spawn_npc_directed

logger = getLogger(__name__)

NODE_NARRATOR = "npc_narrator"


async def _stream_npc_to_socket(
    npc_graph: object,
    input_messages: list[AnyMessage],
    speaker: str,
    sio: socketio.AsyncServer,
    sid: str,
) -> list[AnyMessage]:
    """Stream an NPC graph and emit tokens directly to a Socket.IO client.

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
            await sio.emit("stream_start", {"messageId": message_id, "name": speaker}, to=sid)

    stream = npc_graph.astream(
        {"messages": input_messages}, stream_mode=["messages", "updates"], subgraphs=True,
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
            await sio.emit("stream_token", {"messageId": message_id, "token": msg.content}, to=sid)
            continue

        # Buffer until the leading "{speaker}: " prefix is either stripped or ruled out.
        prefix_buffer += msg.content
        if len(prefix_buffer) >= len(expected) or not expected.startswith(prefix_buffer):
            prefix_stripped = True
            flush = prefix_buffer[len(expected):] if prefix_buffer.startswith(expected) else prefix_buffer
            if flush:
                await sio.emit("stream_token", {"messageId": message_id, "token": flush}, to=sid)

    if not final_messages:
        if message_id is not None:
            # Narration failed after retries: retract the live bubble.
            logger.warning(f"🗑️ {speaker}: no usable narration, retracting streamed bubble {message_id}")
            await sio.emit("stream_end", {"messageId": message_id, "content": ""}, to=sid)
        return []

    final_msg = final_messages[-1]
    display_content = final_msg.content
    if display_content.startswith(f"{speaker}:"):
        display_content = display_content[len(speaker) + 1:].lstrip()

    await ensure_started()
    # Reuse the bubble id so the persisted DB row and the frontend agree.
    final_msg.id = message_id
    await sio.emit("stream_end", {"messageId": message_id, "content": display_content}, to=sid)
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

            npc_graph = spawn_npc_directed(character, ctx.conversation, directive)
            input_messages = [*state.messages, *all_messages]
            try:
                if ctx.sio is not None and ctx.sid is not None:
                    delta = await _stream_npc_to_socket(
                        npc_graph, input_messages, character.name, ctx.sio, ctx.sid,
                    )
                else:
                    result = await npc_graph.ainvoke({"messages": input_messages})
                    delta = result.get("messages", [])[len(input_messages):]
                all_messages.extend(delta)
                logger.info(f"🎭 {directive.name} produced {len(delta)} message(s)")
            except Exception:
                logger.exception(f"💥 NPC graph failed for '{directive.name}'")

        return {"messages": all_messages}

    return npc_executor
