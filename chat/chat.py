from logging import getLogger

import chainlit as cl
from langchain_core.messages import HumanMessage, AIMessage, AIMessageChunk, ToolMessageChunk
from langchain_core.runnables import RunnableConfig

from hephaestus.settings import settings
from hephaestus.logging import init_logger
init_logger()
from hephaestus.langfuse_handler import langfuse_callback_handler


from agents.nonplayer import spawn_npc
from utils.prompts import player_prompt, npc_prompt


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

    character_name = "Xaria"

    # Spawn the NPC agent
    npc_agent = spawn_npc("Xaria", npc_prompt)

    # Store agent in user session
    cl.user_session.set("npc_agent", npc_agent)
    cl.user_session.set("message_history", [])
    cl.user_session.set("character_name", character_name)

    logger.info(f"🎭 Spawned NPC: {character_name}")

    await cl.Message(
        content=f"🎭 **{character_name}** has entered the scene."
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
    final_answer = cl.Message(content="", author=character_name)

    planner_step = cl.Step(name="🧠 Thinking", type="tool")
    tool_step = cl.Step(name="🔧 Using Tools", type="tool")

    for msg, metadata in npc_agent.stream({"messages": [HumanMessage(content=cl_message.content)]},
                                          stream_mode="messages", config=runnable_config):

        node_name = metadata.get("langgraph_node")

        if isinstance(msg, AIMessageChunk):

            if node_name == "npc_narrator":
                # Stream final response to the main message
                await final_answer.stream_token(msg.content)
            elif node_name == "planner":

                async with planner_step as step:
                    await step.stream_token(msg.content)

        elif isinstance(msg, ToolMessageChunk):
            async with tool_step as step:
                await step.stream_token(msg.content)

        else:
            logger.warning(f"🚨 Unknown message type: {type(msg)} from node: {node_name}")

    await final_answer.send()
