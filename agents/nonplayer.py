import asyncio
import re
from logging import getLogger
from typing import TYPE_CHECKING
from uuid import uuid4

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph

from agents.dungeon_master.schemas import STREAM_MESSAGE_ID_KEY, STREAM_SPEAKER_KEY
from database.models import Character as CharacterModel, CharacterMemory
from hephaestus.agent_architectures import (
    AgentSwarmState,
    FailedToSelfCorrect,
    function_to_graph,
    message_delta,
    nudged_agent,
)
from hephaestus.settings import settings
from tools.participants import render_participant_state
from tools.status_effects import character_sheet_by_id
from utils.llm_models import npc_narration
from utils.prompts import narrator_prompt_template

if TYPE_CHECKING:
    from agents.dungeon_master.schemas import DMContext

logger = getLogger(__name__)


def spawn_npc(character: CharacterModel, ctx: "DMContext") -> CompiledStateGraph:
    """🎭 Build a self-correcting NPC graph for use inside ``create_dynamic_daisy_chain``."""
    conv = ctx.conversation
    other_speakers = [c.name for c in conv.characters if c.id != character.id] + [conv.player.name, "Narrator"]
    stop = [f"\n{n}:" for n in other_speakers]
    prefix_re = re.compile(
        rf"^(?:\s*\**\s*{re.escape(character.name)}\s*\**\s*:(?:\s*\*+(?=\s|$))?\s*)+",
        re.IGNORECASE,
    )
    foreign_turn = re.compile(
        rf"^\s*\**\s*(?:{'|'.join(map(re.escape, other_speakers))})\s*\**\s*:",
        re.IGNORECASE | re.MULTILINE,
    )
    nudge_text = (
        f"Your previous reply was invalid: it was empty, contained only a speaker label, or "
        f"spoke a turn on behalf of another participant ({', '.join(other_speakers)}). "
        f"You must now write {character.name}'s OWN turn only: at least one full sentence of "
        f"dialogue or *action*, fully in character as {character.name}. Never write a line "
        f"that begins with another participant's name, and never repeat earlier messages "
        f"from the conversation."
    )
    turn_ctx: dict[str, str] = {}
    last_id: str | None = None

    def is_valid_turn(message: AIMessage) -> bool:
        body = prefix_re.sub("", message.content or "").strip()
        return bool(body) and not foreign_turn.search(body)

    async def npc_narrator(state: AgentSwarmState) -> dict:
        nonlocal last_id
        other_characters = "\n\n\n".join(
            f"**{c.name}**:\n{character_sheet_by_id(c.id)}"
            for c in conv.characters if c.id != character.id
        )
        prompt = await narrator_prompt_template.ainvoke({
            "name": character.name,
            "description": character_sheet_by_id(character.id),
            "other_characters": other_characters,
            "player": ctx.player_sheet,
            "player_name": conv.player.name,
            "location": ctx.location,
            "story_background": ctx.story_background,
            "messages": ctx.combined_messages(state.messages, limit=settings.context_size),
            "dm_guidance": (ctx.plan.action_outcome or "") if ctx.plan else "",
            "lore": ctx.lore,
            "memories": turn_ctx.get("memories", ""),
            "self_state": turn_ctx.get("self_state", ""),
            "player_state": ctx.player_state,
        })
        prefix = f"{character.name}: "
        prompt.messages.append(AIMessage(content=prefix))
        last_id = str(uuid4())
        response = await npc_narration.ainvoke(
            prompt.messages,
            stop=stop,
            config={"metadata": {STREAM_MESSAGE_ID_KEY: last_id, STREAM_SPEAKER_KEY: character.name}},
        )
        response.content = prefix + prefix_re.sub("", response.content or "").strip()
        response.name = character.name
        response.id = last_id
        return {"messages": [response]}

    nudged = nudged_agent(
        function_to_graph(npc_narrator, name="npc_narrator"),
        is_valid_turn,
        nudge_text,
        max_retries=3,
    )

    async def run_npc(state: AgentSwarmState, config: RunnableConfig | None = None) -> dict:
        nonlocal last_id
        last_id = None
        memories_coro = (
            CharacterMemory.recall_by_vector(ctx.campaign_id, character.id, ctx.query_vector)
            if ctx.query_vector is not None
            else CharacterMemory.recall(ctx.campaign_id, character.id, ctx.last_human_query(state.messages, character.name))
        )
        memories, self_state = await asyncio.gather(
            memories_coro,
            asyncio.to_thread(render_participant_state, ctx.campaign_id, character.id, character.name),
        )
        turn_ctx.update(memories=memories, self_state=self_state)
        try:
            res = await nudged.ainvoke({"messages": state.messages}, config)
            delta = message_delta(state.messages, res["messages"])
            logger.info(f"🎭 {character.name} produced {len(delta)} message(s)")
            return {"messages": delta}
        except FailedToSelfCorrect as exc:
            logger.exception(f"🔁 {character.name} failed to self-correct")
            if last_id:
                await ctx.sink.stream_end(last_id, "")
            await ctx.sink.error(str(exc))
            return {"messages": []}
        except Exception:
            logger.exception(f"💥 NPC graph failed for '{character.name}'")
            if last_id:
                await ctx.sink.stream_end(last_id, "")
            return {"messages": []}

    return function_to_graph(run_npc, name=character.name)
