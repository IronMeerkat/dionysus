from logging import getLogger

import chainlit as cl
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from hephaestus.logging import init_logger
init_logger()
from hephaestus.langfuse_handler import langfuse_callback_handler


from agents.agent_swarm import create_agent_swarm
from agents.nonplayer import spawn_npc
from assistant import stream_npc_assistant
from database.models import Player, Character
from database.postgres_connection import session

logger = getLogger(__name__)


@cl.on_chat_start
async def on_start():
    """
    🚀 Initialize the chat session.
    """
    # ========================================
    # PLACEHOLDER: Load your character here
    # Example: character = load_character_from_db(character_id)
    # Then use character.name, character.description, etc.
    # ========================================


    character = session.get(Character, 1)
    player = session.get(Player, 2)

    char_agent = spawn_npc(character.name, character.description, player.description)
    swarm = create_agent_swarm((character.name, char_agent))

    # Store agent in user session
    cl.user_session.set("npc_agent", swarm)
    cl.user_session.set("message_history", [])
    cl.user_session.set("character_name", character.name)

    logger.info(f"🎭 Spawned NPC: {character.name}")

    await cl.Message(
        content=f"🎭 **{character.name}** has entered the scene."
    ).send()


@cl.on_message
async def on_message(cl_message: cl.Message):

    """
    💬 Handle incoming messages and get NPC response.
    """
    npc_agent = cl.user_session.get("npc_agent")
    character_name = cl.user_session.get("character_name")

    if not npc_agent:
        logger.error("❌ No NPC agent found in session!")
        await cl.Message(content="❌ Error: No character loaded. Please restart the chat.").send()
        return

    config = {"configurable": {"thread_id": cl.context.session.id}}
    callbacks = [cl.LangchainCallbackHandler(), langfuse_callback_handler]
    runnable_config = RunnableConfig(callbacks=callbacks, **config)

    stream = npc_agent.stream(
        {"messages": [HumanMessage(content=cl_message.content)]},
        stream_mode="messages",
        config=runnable_config,
    )
    await stream_npc_assistant(character_name, stream)
