import logging

import socketio
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from tools.game_tabletop import tabletop
from agents.dungeon_master import spawn_dungeon_master
from api.stream_handler import SocketStreamHandler
from database.models import Character, Player
from database.postgres_connection import session
from hephaestus.langfuse_handler import langfuse_callback_handler

logger = logging.getLogger(__name__)


def register_events(sio: socketio.AsyncServer) -> None:
    """Register all Socket.IO event handlers on the given server instance."""

    @sio.event
    async def connect(sid: str, environ: dict[str, object]) -> None:
        logger.info("🔌 Client connected: %s", sid)

    @sio.event
    async def disconnect(sid: str) -> None:
        logger.info("🔌 Client disconnected: %s", sid)

    @sio.event
    async def init_session(sid: str, data: dict[str, object]) -> None:
        """Initialise a game session: spawn dungeon master with the chosen player + characters."""
        player_id = data.get("playerId")
        character_ids = data.get("characterIds", [])

        logger.info("🎮 init_session from %s: player=%s characters=%s", sid, player_id, character_ids)

        try:
            player = session.query(Player).filter(Player.id == player_id).first()
            if not player:
                await sio.emit("error", {"message": f"Player with id {player_id} not found."}, to=sid)
                return

            characters = session.query(Character).filter(Character.id.in_(character_ids)).all()
            if not characters:
                await sio.emit("error", {"message": "No valid characters found."}, to=sid)
                return
            
            tabletop.messages = []
            # tabletop.story_background = ""
            # tabletop.location = ""
            # tabletop.lore_world = ""
            tabletop.conversation = None

            dungeon_master = spawn_dungeon_master(*characters, player=player)
            character_list = [c.name for c in characters]

            await sio.save_session(sid, {
                "dungeon_master": dungeon_master,
                "character_list": character_list,
                "player_name": player.name,
            })

            logger.info(
                "🎬 Session ready for %s: player=%s, characters=%s",
                sid, player.name, character_list,
            )

            await sio.emit("session_ready", {
                "player": {"id": player.id, "name": player.name},
                "characters": [{"id": c.id, "name": c.name} for c in characters],
            }, to=sid)

        except Exception:
            logger.exception("💥 Failed to init session for sid=%s", sid)
            await sio.emit("error", {"message": "Failed to initialise game session."}, to=sid)

    @sio.event
    async def send_message(sid: str, data: dict[str, object]) -> None:
        """Handle a user chat message: stream the dungeon master response back."""
        content = data.get("content", "")
        if not content:
            return

        logger.info("💬 send_message from %s: %s", sid, content[:120])

        sess = await sio.get_session(sid)
        dungeon_master = sess.get("dungeon_master") if sess else None
        character_list: list[str] = sess.get("character_list", []) if sess else []

        if not dungeon_master:
            logger.error("❌ No dungeon master in session for sid=%s", sid)
            await sio.emit("error", {"message": "No active session. Please select a player and characters first."}, to=sid)
            return

        config = RunnableConfig(callbacks=[langfuse_callback_handler])

        try:
            stream = dungeon_master.astream(
                {"messages": [HumanMessage(content=content)]},
                stream_mode="messages",
                config=config,
                subgraphs=True,
            )

            handler = SocketStreamHandler(sio, sid, character_list)
            await handler.process(stream)

        except Exception:
            logger.exception("💥 Stream error for sid=%s", sid)
            await sio.emit(
                "error",
                {"message": "The AI connection was interrupted. Please try again."},
                to=sid,
            )
