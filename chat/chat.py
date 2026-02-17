from logging import getLogger

import chainlit as cl
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from hephaestus.logging import init_logger
init_logger()
from hephaestus.langfuse_handler import langfuse_callback_handler

from stream_handler import NPCStreamHandler
from services import build_swarm, load_participants
from wizards import ask_characters, ask_player
from database.models import Conversation


logger = getLogger(__name__)

@cl.on_chat_resume
async def on_chat_resume(thread):
    logger.warning("⏭️ Chat resumed; skipping initialization.")

@cl.on_chat_start
async def on_start():
    """
    🚀 Initialize the chat session via Chainlit AskActionMessage wizard.
    """
    try:
        players, characters = load_participants()

        if not players:
            logger.warning("⚠️ No players found in database.")
            await cl.Message(
                content="⚠️ No players found. Please add players to the database first."
            ).send()
            return

        if not characters:
            logger.warning("⚠️ No characters found in database.")
            await cl.Message(
                content="⚠️ No characters found. Please add characters to the database first."
            ).send()
            return

        player = await ask_player(players)
        selected_characters = await ask_characters(characters)

        conversation = Conversation.create(player, selected_characters)
        swarm, graph_node_to_character_name = build_swarm(player, selected_characters)

        character_name = ", ".join(c.name for c in selected_characters)
        character_ids = [c.id for c in selected_characters]

        cl.user_session.set("npc_agent", swarm)
        cl.user_session.set("message_history", [])
        cl.user_session.set("character_name", character_name)
        cl.user_session.set("conversation_id", conversation.id)
        cl.user_session.set("player_id", player.id)
        cl.user_session.set("character_ids", character_ids)
        cl.user_session.set("graph_node_to_character_name", graph_node_to_character_name)

        logger.info(f"🎬 Conversation {conversation.id} created: player={player.name}, characters=[{character_name}]")
        await cl.Message(
            content=f"🎬 New conversation ready!\n🎮 Player: **{player.name}**\n🎭 Characters: **{character_name}**"
        ).send()
    except TimeoutError as exc:
        logger.exception(f"⏰ Setup wizard timed out: {exc}")
        await cl.Message(
            content="⏰ Setup timed out. Please restart the chat to try again."
        ).send()
    except Exception as exc:
        logger.exception(f"❌ Failed to initialize chat session: {exc}")
        await cl.Message(
            content="❌ Failed to initialize conversation setup. Please restart chat."
        ).send()


@cl.on_message
async def on_message(cl_message: cl.Message):
    """
    💬 Handle incoming messages and get NPC response.
    """
    npc_agent = cl.user_session.get("npc_agent")
    # character_name = cl.user_session.get("character_name")

    if not npc_agent:
        logger.error("❌ No NPC agent found in session!")
        await cl.Message(content="❌ Error: No character loaded. Please restart the chat.").send()
        return

    config = {"configurable": {"thread_id": cl.context.session.id}}
    callbacks = [cl.LangchainCallbackHandler(), langfuse_callback_handler]
    runnable_config = RunnableConfig(callbacks=callbacks, **config)

    try:
        stream = npc_agent.stream(
            {"messages": [HumanMessage(content=cl_message.content)]},
            stream_mode="messages",
            config=runnable_config,
            subgraphs=True,
        )

        mapping = cl.user_session.get("graph_node_to_character_name", {})
        if not mapping:
            logger.warning("❌ No mapping found in session!")
        handler = NPCStreamHandler(mapping)
        await handler.process(stream)
    except Exception as exc:
        logger.exception(f"❌ Stream error: {exc}")
        await cl.Message(
            content="⚠️ The AI connection was interrupted. Please try sending your message again."
        ).send()
