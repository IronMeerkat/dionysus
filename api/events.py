import logging

import socketio
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from tools.game_tabletop import tabletop
from agents.dungeon_master import dungeon_master
from api.stream_handler import SocketStreamHandler
from hephaestus.langfuse_handler import langfuse_callback_handler

logger = logging.getLogger(__name__)


def register_events(sio: socketio.AsyncServer) -> None:
    """Register all Socket.IO event handlers on the given server instance."""

    @sio.event
    async def connect(sid: str, environ: dict[str, object]) -> None:
        logger.info(f"🔌 Client connected: {sid}")

    @sio.event
    async def disconnect(sid: str) -> None:
        logger.info(f"🔌 Client disconnected: {sid}")

    @sio.event
    async def init_session(sid: str, data: dict[str, object]) -> None:
        """Initialise a game session: spawn dungeon master with the chosen player + characters."""

        character_list = [c.name for c in tabletop.characters]
        logger.info(f"🎮 init_session from {sid}: player={tabletop.player.name} characters={character_list}")

        try:

            await sio.emit("session_ready", {
                "player": {"id": tabletop.player.id, "name": tabletop.player.name},
                "characters": [{"id": c.id, "name": c.name} for c in tabletop.characters],
            }, to=sid)

        except Exception:
            logger.exception(f"💥 Failed to init session for sid={sid}")
            await sio.emit("error", {"message": "Failed to initialise game session."}, to=sid)

    @sio.event
    async def send_message(sid: str, data: dict[str, object]) -> None:
        """Handle a user chat message: stream the dungeon master response back."""
        content = data.get("content", "")
        if not content:
            return

        logger.info(f"💬 send_message from {sid}: {content[:120]}")


        config = RunnableConfig(callbacks=[langfuse_callback_handler])

        try:
            stream = dungeon_master.graph.astream(
                {"messages": [HumanMessage(content=content, name=tabletop.player.name)]},
                stream_mode="messages",
                config=config,
                subgraphs=True,
            )

            handler = SocketStreamHandler(sio, sid, [c.name for c in tabletop.characters])
            await handler.process(stream)

        except Exception:
            logger.exception(f"💥 Stream error for sid={sid}")
            await sio.emit(
                "error",
                {"message": "The AI connection was interrupted. Please try again."},
                to=sid,
            )
