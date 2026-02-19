from logging import getLogger

import chainlit as cl
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from hephaestus.logging import init_logger
init_logger()
from hephaestus.agent_architectures import create_daisy_chain
from hephaestus.langfuse_handler import langfuse_callback_handler

from agents.dungeon_master import spawn_dungeon_master
from stream_handler import NPCStreamHandler
from wizards import ask_characters, ask_player
from database.models import Conversation
from database.postgres_connection import session
from database.models import Player, Character

logger = getLogger(__name__)


def load_participants():
    players = session.query(Player.id, Player.name).order_by(Player.id.asc()).all()
    characters = session.query(Character.id, Character.name).order_by(Character.id.asc()).all()
    return players, characters

@cl.on_chat_resume
async def on_chat_resume(thread):
    logger.warning("⏭️ Chat resumed; skipping initialization.")

@cl.on_chat_start
async def on_start():
    """
    🚀 Initialize the chat session via Chainlit AskActionMessage wizard.
    """
    try:

        if cl.user_session.get("conversation_id"):
            logger.warning("⏭️ Chat already initialized; skipping initialization.")
            return

        players, characters = load_participants()

        if not players:
            raise ValueError("No players found in database.")

        if not characters:
            raise ValueError("No characters found in database.")

        player = await ask_player(players)
        selected_characters = await ask_characters(characters)

        character_list = [c.name for c in selected_characters]
        dungeon_master = spawn_dungeon_master(*selected_characters, player=player)

        character_names = ", ".join(character_list)

        cl.user_session.set("dungeon_master", dungeon_master)
        cl.user_session.set("message_history", [])
        cl.user_session.set("player_id", player.id)
        cl.user_session.set("character_list", character_list)

        await cl.Message(
            content=f"🎬 New conversation ready!\n🎮 Player: **{player.name}**\n🎭 Characters: **{character_names}**"
        ).send()
    except TimeoutError as exc:
        logger.exception(f"⏰ Setup wizard timed out: {exc}")
        await cl.Message(
            content="⏰ Setup timed out. Please restart the chat to try again."
        ).send()
    except Exception as exc:
        logger.exception(f"❌ Failed to initialize chat session: {exc}")
        await cl.Message(
            content=f"❌ Failed to initialize conversation setup: {exc}. Please restart chat."
        ).send()


@cl.on_message
async def on_message(cl_message: cl.Message):
    """
    💬 Handle incoming messages and get NPC response.
    """
    dungeon_master = cl.user_session.get("dungeon_master")

    if not dungeon_master:
        logger.error("❌ No NPC agent found in session!")
        await cl.Message(content="❌ Error: No character loaded. Please restart the chat.").send()
        return

    config = {"configurable": {"thread_id": cl.context.session.id}}
    runnable_config = RunnableConfig(callbacks=[langfuse_callback_handler], **config)

    try:
        stream = dungeon_master.astream(
            {"messages": [HumanMessage(content=cl_message.content)]},
            stream_mode="messages",
            config=runnable_config,
            subgraphs=True,
        )

        character_list = cl.user_session.get("character_list", [])
        if not character_list:
            logger.warning("❌ No character list found in session!")
        handler = NPCStreamHandler(character_list)
        await handler.process(stream)
    except Exception as exc:
        logger.exception(f"❌ Stream error: {exc}")
        await cl.Message(
            content="⚠️ The AI connection was interrupted. Please try sending your message again."
        ).send()
