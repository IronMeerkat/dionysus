import logging
from uuid import uuid4

import socketio
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from agents.dungeon_master import NARRATOR_NAME, spawn_dungeon_master
from api.stream_handler import SocketStreamHandler
from database.models.conversation import Conversation
from database.postgres_connection import db_session
from hephaestus.langfuse_handler import langfuse_callback_handler

logger = logging.getLogger(__name__)

# Live game sessions: conversation_id -> the detached Conversation snapshot a
# socket client is playing on. REST endpoints that mutate messages use this to
# patch the in-memory message buffer -- the old shared-session identity map
# used to hand them the very same object, but per-task sessions make every
# query return a distinct instance.
_LIVE_CONVERSATIONS: dict[int, Conversation] = {}


def get_live_conversation(conversation_id: int) -> Conversation | None:
    """🎮 The in-memory Conversation a live socket session is playing, if any."""
    return _LIVE_CONVERSATIONS.get(conversation_id)


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
            conversation = Conversation.get(id=conversation_id)
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
            _LIVE_CONVERSATIONS[conversation.id] = conversation

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
            conversation = Conversation.get(id=data.get("conversation_id"))
            if conversation is None:
                logger.error(f"❌ No conversation found for sid={sid}")
                await sio.emit("error", {"message": "No conversation found."}, to=sid)
                return
            await sio.save_session(sid, {
                "conversation": conversation,
            })
            _LIVE_CONVERSATIONS[conversation.id] = conversation
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


        # NPC build negotiation loops add several super-steps per introduced
        # NPC, so the default recursion limit of 25 is too tight.
        config = RunnableConfig(callbacks=[langfuse_callback_handler], recursion_limit=80)

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

            # NPC bubbles already stream with the same UUID that gets persisted,
            # so only DM narrator messages need their ids remapped.
            if handler.message_ids:
                new_ai_msgs = [m for m in conversation.messages if m.role == "ai"][pre_ai_count:]
                narrator_msgs = [m for m in new_ai_msgs if m.speaker_name == NARRATOR_NAME]
                id_map = [
                    {"oldId": stream_id, "newId": str(db_msg.id)}
                    for stream_id, db_msg in zip(handler.message_ids, narrator_msgs)
                ]
                if id_map:
                    await sio.emit("messages_persisted", {"mapping": id_map}, to=sid)

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
