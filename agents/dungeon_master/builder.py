"""One-shot NPC builds: a single structured call designs the card, code persists it.

Replaces the old DM <-> npc-builder negotiation loop (2-6+ calls per NPC)
with one ``CharacterCard`` structured-output call plus deterministic
persistence. The registrar is unchanged: it registers whatever the name
lookup finds and logs loudly when a failed build left nothing to register.
"""
import asyncio
from logging import getLogger

from langchain_core.messages import HumanMessage, SystemMessage

from agents.dungeon_master.context import DMContext
from agents.dungeon_master.schemas import CharacterCard, DungeonMasterState
from agents.skills.registry import skill_registry
from database.models import CampaignParticipant, Character as CharacterModel
from database.models.lore import LoreEntry, World
from database.postgres_connection import db_session
from tools.npc_management import create_character
from tools.status_effects import set_character_status_effect
from utils.llm_models import skilled_agent_model

logger = getLogger(__name__)


def register_character_in_scene(ctx: DMContext, character: CharacterModel) -> None:
    """🎭 Add a character to the conversation and ensure its campaign state row.

    Shared by ``npc_registrar`` (post-build) and the planner's semantic
    dedup (an introduction that matched an existing character skips the
    build loop but still joins the scene exactly the same way).
    """
    ctx.conversation.add_character(character)
    ctx.conversation._npcs_introduced = True
    CampaignParticipant.get_or_create(campaign_id=ctx.campaign_id, character_id=character.id)
    logger.info(
        f"🎭 NPC '{character.name}' introduced to scene "
        f"(campaign {ctx.campaign_id}, state row ensured)"
    )


def make_builder_nodes(ctx: DMContext) -> dict:
    build_llm = skilled_agent_model.with_structured_output(CharacterCard, strict=True)

    async def _skill_system_prompt() -> str:
        """The npc-building skill body rendered with the world's lore listing."""
        world_name = ctx.campaign.lore_world
        world = await asyncio.to_thread(World.get_world_by_name, world_name)
        if world is None:
            logger.warning(f"⚠️ World '{world_name}' not found for NPC building; lore listing empty")
            lore = "(no lore entries)"
        else:
            entries = await asyncio.to_thread(LoreEntry.preview_entries, world)
            lore = "\n".join(f"- id={e['id']} | title='{e['title']}'" for e in entries) or "(no lore entries)"
        return skill_registry.get("npc-building").body.format(world_name=world_name, lore=lore)

    def _validate(name: str, card: CharacterCard) -> str | None:
        """Deterministic card validation; returns the rejection reason or None."""
        description = (card.description or "").strip()
        if "[character" not in description.lower():
            return "the description is not a W++ card (missing the [character ...] block)"
        if name.lower() not in description.lower():
            return f"the card never names the character '{name}'"
        return None

    async def npc_builder_caller(state: DungeonMasterState) -> dict:
        """🏗️ One structured call designs the NPC at the head of the build
        queue; code persists the card and any sheet effects.

        One corrective retry on validation failure, then the introduction
        is abandoned loudly -- never a half-built NPC.
        """
        intro = state.build_queue[0]
        messages = [
            SystemMessage(content=await _skill_system_prompt()),
            HumanMessage(content=(
                f"Design an NPC named exactly '{intro.name}' in one shot -- no questions, no "
                f"tool calls. Build instructions:\n{intro.build_instructions}\n\n"
                f"Lore relevant to the current scene:\n{state.lore}"
            )),
        ]
        card: CharacterCard | None = None
        for attempt in (1, 2):
            try:
                candidate: CharacterCard = await build_llm.ainvoke(messages)
            except Exception:
                logger.exception(f"💥 NPC build call failed for '{intro.name}' (attempt {attempt}/2)")
                continue
            error = _validate(intro.name, candidate)
            if error is None:
                card = candidate
                break
            logger.warning(f"⚠️ NPC card for '{intro.name}' rejected (attempt {attempt}/2): {error}")
            messages.append(HumanMessage(content=(
                f"Your card was rejected: {error}. Resubmit the full corrected card."
            )))
        if card is None:
            logger.error(f"🛑 Building '{intro.name}' failed; skipping persistence (registrar logs the no-show)")
            return {"messages": []}

        created = await asyncio.to_thread(
            create_character.invoke, {"name": intro.name, "description": card.description.strip()}
        )
        if created.startswith("❌"):
            logger.error(f"🏗️ create_character failed for '{intro.name}': {created}")
            return {"messages": []}
        logger.info(f"🏗️ {created}")
        for effect in card.status_effects:
            try:
                await asyncio.to_thread(set_character_status_effect.invoke, {
                    "character_name": intro.name,
                    "name": effect.name,
                    "description": effect.note or "",
                    "affects": effect.affects or "",
                    "roll_modifier": effect.roll_modifier,
                    "advantage": effect.advantage,
                })
            except Exception:
                logger.exception(f"💥 Failed to set status effect '{effect.name}' on '{intro.name}'")
        return {"messages": []}

    async def npc_registrar(state: DungeonMasterState) -> dict:
        """🎭 Register the NPC at the head of the build queue into the scene
        and advance the queue.

        The NPC is added to the conversation and given a ``CampaignParticipant``
        state row the moment they join -- whether they were just built fresh
        or already existed in the database from a prior session. The character
        lookup is the source of truth, so a returning NPC that the builder did
        not re-create still gets registered into this campaign.
        """
        intro = state.build_queue[0]

        with db_session() as s:
            character = s.query(CharacterModel).filter(
                CharacterModel.name == intro.name
            ).first()
        if character is None:
            logger.error(
                f"❌ NPC '{intro.name}' not found in DB; cannot register into "
                f"campaign {ctx.campaign_id}"
            )
        else:
            register_character_in_scene(ctx, character)

        return {"messages": [], "build_queue": state.build_queue[1:]}

    return {
        "npc_builder_caller": npc_builder_caller,
        "npc_registrar": npc_registrar,
    }
