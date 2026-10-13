"""Opening narrator node and mid-turn one-shot NPC builder."""
import asyncio
from logging import getLogger

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph.state import CompiledStateGraph

from agents.dungeon_master.schemas import CharacterCard, DMContext, NPCIntroduction, narrate_beats
from agents.skilled_agent import skill_registry
from database.models import Character as CharacterModel, World
from database.models.lore import LoreEntry
from database.postgres_connection import db_session
from database.session_utils import embedder
from hephaestus.agent_architectures import AgentSwarmState, function_to_graph
from hephaestus.settings import settings
from tools.npc_management import create_character
from tools.status_effects import set_character_status_effect
from utils.llm_models import skilled_agent_model

logger = getLogger(__name__)


async def _build_and_register_npc(ctx: DMContext, intro: NPCIntroduction) -> None:
    """🏗️ Deduplicate or one-shot build an introduced NPC and register them into the scene."""
    tau = settings.memory.dedup.tau_dedup
    try:
        vec = await embedder.aembed_query(CharacterModel.embedding_text(intro.name, intro.build_instructions))
        exclude = (ctx.player_id,) if ctx.player_id is not None else ()
        neighbors = await asyncio.to_thread(CharacterModel.nearest_by_vector, vec, 1, exclude)
        if neighbors and neighbors[0][1] <= tau:
            character, dist = neighbors[0]
            logger.info(f"♻️ Intro '{intro.name}' matched '{character.name}' (L2={dist:.3f} <= {tau}); reusing")
            intro.name = character.name
            ctx.register_character(character)
            return
    except Exception:
        logger.exception(f"💥 Dedup search failed for intro '{intro.name}'; proceeding with build")

    world_name = ctx.conversation.campaign.lore_world
    world = await asyncio.to_thread(World.get_world_by_name, world_name)
    entries = await asyncio.to_thread(LoreEntry.preview_entries, world) if world else []
    lore_list = "\n".join(f"- id={e['id']} | title='{e['title']}'" for e in entries) or "(no lore entries)"
    sys_prompt = skill_registry.get("npc-building").body.format(world_name=world_name, lore=lore_list)
    messages = [
        SystemMessage(content=sys_prompt),
        HumanMessage(content=(
            f"Design an NPC named exactly '{intro.name}' in one shot -- no questions, no tool calls. "
            f"Build instructions:\n{intro.build_instructions}\n\nLore relevant to the current scene:\n{ctx.lore}"
        )),
    ]
    build_llm = skilled_agent_model.with_structured_output(CharacterCard, strict=True)
    card: CharacterCard | None = None
    for attempt in (1, 2):
        try:
            cand: CharacterCard = await build_llm.ainvoke(messages)
        except Exception:
            logger.exception(f"💥 NPC build call failed for '{intro.name}' (attempt {attempt}/2)")
            continue
        desc = (cand.description or "").strip().lower()
        err = (
            "missing [character ...] block" if "[character" not in desc
            else f"card never names '{intro.name}'" if intro.name.lower() not in desc
            else None
        )
        if err is None:
            card = cand
            break
        logger.warning(f"⚠️ NPC card for '{intro.name}' rejected (attempt {attempt}/2): {err}")
        messages.append(HumanMessage(content=f"Your card was rejected: {err}. Resubmit the full corrected card."))

    if card is None:
        logger.error(f"🛑 Building '{intro.name}' failed; skipping persistence")
        return

    created = await asyncio.to_thread(
        create_character.invoke, {"name": intro.name, "description": card.description.strip()}
    )
    if created.startswith("❌"):
        logger.error(f"🏗️ create_character failed for '{intro.name}': {created}")
        return
    logger.info(f"🏗️ {created}")
    for eff in card.status_effects:
        try:
            await asyncio.to_thread(set_character_status_effect.invoke, {
                "character_name": intro.name,
                "name": eff.name,
                "description": eff.note or "",
                "affects": eff.affects or "",
                "roll_modifier": eff.roll_modifier,
                "advantage": eff.advantage,
            })
        except Exception:
            logger.exception(f"💥 Failed to set status effect '{eff.name}' on '{intro.name}'")

    with db_session() as s:
        character = s.query(CharacterModel).filter(CharacterModel.name == intro.name).first()
    if character is None:
        logger.error(f"❌ NPC '{intro.name}' not found in DB after build")
    else:
        ctx.register_character(character)


def spawn_dm_narrator_opening(ctx: DMContext) -> CompiledStateGraph:
    async def dm_narrator_opening(state: AgentSwarmState) -> dict:
        plan = ctx.plan
        if ctx.ooc or not plan:
            return {"messages": []}
        notes: list[tuple[str, str]] = []
        if plan.action_outcome and not ctx.conversation.characters and not plan.npcs_to_introduce:
            notes.append(("Action outcome", plan.action_outcome))
            ctx.outcome_narrated = True
        if plan.time_location_update:
            notes.append(("Scene change", plan.time_location_update))
        if plan.opening_narration:
            notes.append(("Opening narration", plan.opening_narration))
        notes.extend(("New character enters", i.entrance_narration) for i in plan.npcs_to_introduce)

        build_tasks = [_build_and_register_npc(ctx, intro) for intro in plan.npcs_to_introduce]
        results = await asyncio.gather(narrate_beats(ctx, notes, state.messages), *build_tasks)
        return {"messages": results[0]}

    return function_to_graph(dm_narrator_opening, name="dm_narrator_opening")
