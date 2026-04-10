import logging
from uuid import uuid4

import socketio
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from agents.dungeon_master import spawn_dungeon_master
from api.stream_handler import SocketStreamHandler
from database.models.conversation import Conversation
from database.postgres_connection import session as db_session
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
        """Initialise a game session from a conversation_id.

        Loads the Conversation from DB, builds the agent graph, and
        stores both in the SocketIO session for this client.
        """

        conversation_id = data.get("conversation_id")
        if conversation_id is None:
            await sio.emit("error", {"message": "conversation_id is required."}, to=sid)
            return

        try:
            conversation = db_session.query(Conversation).filter(Conversation.id == conversation_id).first()
            if conversation is None:
                await sio.emit("error", {"message": f"Conversation {conversation_id} not found."}, to=sid)
                return

            lc_messages = conversation.langchain_messages()
            window = min(12, len(lc_messages))
            conversation.message_buffer = lc_messages[-window:]

            graph = spawn_dungeon_master(conversation, sio=sio, sid=sid)

            await sio.save_session(sid, {
                "conversation": conversation,
                "graph": graph,
            })

            character_list = [c.name for c in conversation.characters]
            logger.info(f"🎮 init_session from {sid}: player={conversation.player.name} characters={character_list}")

            await sio.emit("session_ready", {
                "conversation_id": conversation.id,
                "player": {"id": conversation.player.id, "name": conversation.player.name},
                "characters": [{"id": c.id, "name": c.name} for c in conversation.characters],
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

        sock_session = await sio.get_session(sid)
        conversation: Conversation | None = sock_session.get("conversation")
        graph = sock_session.get("graph")

        if conversation is None:
            conversation = db_session.query(Conversation).filter(Conversation.id == data.get("conversation_id")).first()
            if conversation is None:
                logger.error(f"❌ No conversation found for sid={sid}")
                await sio.emit("error", {"message": "No conversation found."}, to=sid)
                return
            await sio.save_session(sid, {
                "conversation": conversation,
            })
        if conversation.id != data.get("conversation_id"):
            logger.error(f"❌ Conversation ID mismatch for sid={sid}")
            await sio.emit("error", {"message": "Conversation ID mismatch."}, to=sid)
            return
        if graph is None:
            logger.warning(f"🔄 No graph found for sid={sid}, spawning new graph")
            graph = spawn_dungeon_master(conversation, sio=sio, sid=sid)
            await sio.save_session(sid, {
                "conversation": conversation,
                "graph": graph,
            })

        msg_id = str(uuid4())
        await sio.emit("message_created", {"messageId": msg_id}, to=sid)
        logger.info(f"🪪 message_created emitted: id={msg_id}")


        config = RunnableConfig(callbacks=[langfuse_callback_handler])

        try:
            stream = graph.astream(
                {"messages": [HumanMessage(content=content, name=conversation.player.name, id=msg_id)]},
                stream_mode="messages",
                config=config,
                subgraphs=True,
            )

            pre_ai_count = sum(1 for m in conversation.messages if m.role == "ai")

            character_list = [c.name for c in conversation.characters]
            handler = SocketStreamHandler(sio, sid, character_list)
            await handler.process(stream)

            npc_streamed_ids: list[str] = getattr(conversation, "_streamed_npc_ids", [])
            all_stream_ids = handler.message_ids + npc_streamed_ids

            if all_stream_ids:
                new_ai_msgs = [m for m in conversation.messages if m.role == "ai"][pre_ai_count:]
                id_map = [
                    {"oldId": stream_id, "newId": str(db_msg.id)}
                    for stream_id, db_msg in zip(all_stream_ids, new_ai_msgs)
                ]
                await sio.emit("messages_persisted", {"mapping": id_map}, to=sid)

            conversation._streamed_npc_ids = []

            if getattr(conversation, "_npcs_introduced", False):
                conversation._npcs_introduced = False
                graph = spawn_dungeon_master(conversation, sio=sio, sid=sid)
                await sio.save_session(sid, {
                    "conversation": conversation,
                    "graph": graph,
                })
                logger.info(f"🔄 Graph rebuilt after NPC introduction for sid={sid}")

        except Exception:
            logger.exception(f"💥 Stream error for sid={sid}")
            await sio.emit(
                "error",
                {"message": "The AI connection was interrupted. Please try again."},
                to=sid,
            )
