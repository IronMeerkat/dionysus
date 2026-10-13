"""Out-of-character (OOC) responder node for the DM pipeline."""
from logging import getLogger
from uuid import uuid4

from langchain_core.messages import AIMessage
from langgraph.graph.state import CompiledStateGraph

from agents.dungeon_master.schemas import DMContext, NARRATOR_NAME, STREAM_MESSAGE_ID_KEY
from hephaestus.agent_architectures import AgentSwarmState, function_to_graph
from utils.llm_models import dm_ooc_model
from utils.prompts import dm_ooc_responder_prompt_template

logger = getLogger(__name__)


def spawn_ooc_responder(ctx: DMContext) -> CompiledStateGraph:
    async def ooc_responder(state: AgentSwarmState) -> dict:
        if not ctx.ooc:
            return {"messages": []}
        prompt = await dm_ooc_responder_prompt_template.ainvoke({
            "lore": ctx.lore,
            "world_events": ctx.world_events,
            "open_threads": ctx.open_threads,
            "location": ctx.location,
            "world_clock": ctx.world_clock,
            "story_background": ctx.story_background,
            "player_name": ctx.conversation.player.name,
            "messages": ctx.combined_messages(state.messages),
        })
        prefix = f"{NARRATOR_NAME}: "
        prompt.messages.append(AIMessage(content=prefix))
        message_id = str(uuid4())
        try:
            response = await dm_ooc_model.ainvoke(
                prompt, config={"metadata": {STREAM_MESSAGE_ID_KEY: message_id}}
            )
        except Exception:
            logger.exception("💥 OOC responder failed")
            await ctx.sink.stream_end(message_id, "")
            return {"messages": []}
        content = (response.content or "").strip()
        while content.startswith(prefix):
            content = content[len(prefix):].lstrip()
        if not content:
            logger.error("💀 OOC responder produced an empty answer, skipping")
            await ctx.sink.stream_end(message_id, "")
            return {"messages": []}
        return {"messages": [AIMessage(content=f"{prefix}{content}", name=NARRATOR_NAME, id=message_id)]}

    return function_to_graph(ooc_responder, name="ooc_responder")
