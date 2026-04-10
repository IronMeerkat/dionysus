import logging

import socketio
from langchain_core.messages import AIMessage, AIMessageChunk, AnyMessage, HumanMessage, ToolMessage, ToolMessageChunk
from langchain_core.runnables import RunnableConfig

from agents.npc_builder import spawn_npc_builder
from hephaestus.langfuse_handler import langfuse_callback_handler

logger = logging.getLogger(__name__)

NPC_BUILDER_NS = "/npc-builder"


def register_npc_builder_events(sio: socketio.AsyncServer) -> None:
    """Register Socket.IO event handlers on the /npc-builder namespace."""

    @sio.event(namespace=NPC_BUILDER_NS)
    async def connect(sid: str, environ: dict[str, object]) -> None:
        logger.info(f"🔌 [npc-builder] Client connected: {sid}")

    @sio.event(namespace=NPC_BUILDER_NS)
    async def disconnect(sid: str) -> None:
        logger.info(f"🔌 [npc-builder] Client disconnected: {sid}")

    @sio.event(namespace=NPC_BUILDER_NS)
    async def init_npc_builder(sid: str, data: dict[str, object]) -> None:
        world_name = data.get("world_name")
        if not world_name or not isinstance(world_name, str):
            await sio.emit("error", {"message": "world_name is required."}, to=sid, namespace=NPC_BUILDER_NS)
            return

        try:
            graph = spawn_npc_builder(world_name)
            await sio.save_session(sid, {
                "graph": graph,
                "world_name": world_name,
                "history": [],
            }, namespace=NPC_BUILDER_NS)

            logger.info(f"🏗️ [npc-builder] Session initialized for world '{world_name}' (sid={sid})")
            await sio.emit("npc_builder_session_ready", {"world_name": world_name}, to=sid, namespace=NPC_BUILDER_NS)

        except Exception:
            logger.exception(f"💥 [npc-builder] Failed to init session for sid={sid}")
            await sio.emit("error", {"message": "Failed to initialise NPC builder session."}, to=sid, namespace=NPC_BUILDER_NS)

    @sio.event(namespace=NPC_BUILDER_NS)
    async def npc_builder_message(sid: str, data: dict[str, object]) -> None:
        content = data.get("content", "")
        if not content:
            return

        logger.info(f"💬 [npc-builder] message from {sid}: {str(content)[:120]}")

        sock_session = await sio.get_session(sid, namespace=NPC_BUILDER_NS)
        graph = sock_session.get("graph")
        history: list[AnyMessage] = sock_session.get("history", [])
        world_name: str = sock_session.get("world_name", "")

        if graph is None:
            await sio.emit("error", {"message": "No NPC builder session active. Call init_npc_builder first."}, to=sid, namespace=NPC_BUILDER_NS)
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

                if isinstance(msg, AIMessageChunk) and langgraph_node == "builder_agent":
                    if msg.content:
                        token = str(msg.content)
                        collected_text += token
                        await sio.emit("npc_builder_token", {"token": token}, to=sid, namespace=NPC_BUILDER_NS)

                elif isinstance(msg, (ToolMessage, ToolMessageChunk)):
                    tool_content = str(msg.content) if msg.content else ""
                    if "Created character" in tool_content or tool_content == "true":
                        name = tool_content.split("'")[1] if "'" in tool_content else "NPC"
                        await sio.emit("npc_builder_created", {"name": name}, to=sid, namespace=NPC_BUILDER_NS)
                        logger.info(f"🎭 [npc-builder] Emitted npc_builder_created for '{name}'")

            if collected_text:
                history.append(AIMessage(content=collected_text))

            await sio.save_session(sid, {
                "graph": graph,
                "world_name": world_name,
                "history": history,
            }, namespace=NPC_BUILDER_NS)

        except Exception:
            logger.exception(f"💥 [npc-builder] Stream error for sid={sid}")
            await sio.emit("error", {"message": "An error occurred while processing your request."}, to=sid, namespace=NPC_BUILDER_NS)
        finally:
            await sio.emit("npc_builder_done", {}, to=sid, namespace=NPC_BUILDER_NS)
            logger.debug(f"🏁 [npc-builder] npc_builder_done emitted for sid={sid}")
