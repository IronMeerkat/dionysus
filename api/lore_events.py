import logging

import socketio
from langchain_core.messages import AIMessage, AIMessageChunk, AnyMessage, HumanMessage, ToolMessage, ToolMessageChunk
from langchain_core.runnables import RunnableConfig

from agents.lore_creator import spawn_lore_creator
from hephaestus.langfuse_handler import langfuse_callback_handler

logger = logging.getLogger(__name__)

LORE_NS = "/lore"


def register_lore_events(sio: socketio.AsyncServer) -> None:
    """Register Socket.IO event handlers on the /lore namespace."""

    @sio.event(namespace=LORE_NS)
    async def connect(sid: str, environ: dict[str, object]) -> None:
        logger.info(f"🔌 [lore] Client connected: {sid}")

    @sio.event(namespace=LORE_NS)
    async def disconnect(sid: str) -> None:
        logger.info(f"🔌 [lore] Client disconnected: {sid}")

    @sio.event(namespace=LORE_NS)
    async def init_lore_session(sid: str, data: dict[str, object]) -> None:
        world_name = data.get("world_name")
        if not world_name or not isinstance(world_name, str):
            await sio.emit("error", {"message": "world_name is required."}, to=sid, namespace=LORE_NS)
            return

        try:
            graph = spawn_lore_creator(world_name)
            await sio.save_session(sid, {
                "graph": graph,
                "world_name": world_name,
                "history": [],
            }, namespace=LORE_NS)

            logger.info(f"🌍 [lore] Session initialized for world '{world_name}' (sid={sid})")
            await sio.emit("lore_session_ready", {"world_name": world_name}, to=sid, namespace=LORE_NS)

        except Exception:
            logger.exception(f"💥 [lore] Failed to init session for sid={sid}")
            await sio.emit("error", {"message": "Failed to initialise lore session."}, to=sid, namespace=LORE_NS)

    @sio.event(namespace=LORE_NS)
    async def lore_message(sid: str, data: dict[str, object]) -> None:
        content = data.get("content", "")
        if not content:
            return

        logger.info(f"💬 [lore] message from {sid}: {str(content)[:120]}")

        sock_session = await sio.get_session(sid, namespace=LORE_NS)
        graph = sock_session.get("graph")
        history: list[AnyMessage] = sock_session.get("history", [])
        world_name: str = sock_session.get("world_name", "")

        if graph is None:
            await sio.emit("error", {"message": "No lore session active. Call init_lore_session first."}, to=sid, namespace=LORE_NS)
            return

        human_msg = HumanMessage(content=str(content))
        history.append(human_msg)

        config = RunnableConfig(callbacks=[langfuse_callback_handler])
        collected_text = ""

        try:
            stream = graph.astream(
                {"messages": list(history)},
                stream_mode="messages",
                config=config,
                subgraphs=True,
            )

            async for item in stream:
                namespace_tuple, (msg, metadata) = item
                langgraph_node = metadata.get("langgraph_node", "")

                if isinstance(msg, AIMessageChunk) and langgraph_node == "lore_agent":
                    if msg.content:
                        token = str(msg.content)
                        collected_text += token
                        await sio.emit("lore_token", {"token": token}, to=sid, namespace=LORE_NS)

                elif isinstance(msg, (ToolMessage, ToolMessageChunk)):
                    tool_content = str(msg.content) if msg.content else ""
                    if "✅ Saved" in tool_content or "📦 Queued" in tool_content:
                        title = tool_content.split("'")[1] if "'" in tool_content else "entry"
                        await sio.emit("lore_saving", {"title": title}, to=sid, namespace=LORE_NS)
                        logger.info(f"📜 [lore] Emitted lore_saving for '{title}'")

            if collected_text:
                history.append(AIMessage(content=collected_text))

            await sio.save_session(sid, {
                "graph": graph,
                "world_name": world_name,
                "history": history,
            }, namespace=LORE_NS)

        except Exception:
            logger.exception(f"💥 [lore] Stream error for sid={sid}")
            await sio.emit("error", {"message": "An error occurred while processing your request."}, to=sid, namespace=LORE_NS)
        finally:
            await sio.emit("lore_done", {}, to=sid, namespace=LORE_NS)
            logger.debug(f"🏁 [lore] lore_done emitted for sid={sid}")
