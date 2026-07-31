"""🎯 Skill-driven classifiers: one helper + thin wrappers for the DM's cheap
structured hops (intent routing, continuity checking, scene-change detection).

Each classifier's instructions live in a SKILL.md file (see ``skills/``);
this module owns only prompt assembly, the structured-output call, and
fail-secure recovery (catch → log → return None / go back — never invent success).
"""
import asyncio
from logging import getLogger
from typing import Any, TypeVar

from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel

from agents.dungeon_master.context import DMContext
from agents.dungeon_master.schemas import ContinuityVerdict, DungeonMasterState, IntentReading
from agents.skills.registry import skill_registry
from database.models import World
from database.models.lore import LoreEntry
from database.session_utils import embedder
from hephaestus.settings import settings
from utils.llm_models import dm_continuity_model, dm_intent_model

logger = getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# First plan + one repaired plan; after that we proceed regardless.
MAX_PLAN_ATTEMPTS = 2
# How much recent conversation the cheap classifier hops get to see.
ROUTER_CONTEXT_WINDOW = 12
CONTINUITY_CONTEXT_WINDOW = 12
# How many lore documents vector recall pulls per turn.
LORE_TOP_K = settings.memory.recall.lore_top_k


async def run_classifier(skill: str, model: BaseChatModel, schema: type[T], variables: dict[str, Any], *, label: str) -> T | None:
    """Render a classifier skill and call the model with structured output.

    Fail-secure: on exception or a ``None`` structured result, log and return
    ``None``. Never invent a fake classification. Callers must handle ``None``
    by recovering (skip / go back) — not by pretending the hop succeeded.
    """
    prompt = await skill_registry.render(skill).ainvoke(variables)
    llm = model.with_structured_output(schema, strict=True)
    try:
        result = await llm.ainvoke(prompt)
    except Exception:
        logger.exception(f"💥 [{label}] classifier '{skill}' failed; returning None")
        return None
    if result is None:
        logger.warning(f"⚠️ [{label}] classifier '{skill}' returned None; not inventing a result")
        return None
    return result


async def _retrieve_lore(ctx: DMContext, state: DungeonMasterState, summary: str) -> str:
    """🔍 Vector lore recall: embed the player's message (anchored by the
    intent summary) and pull the world's closest entries -- no title catalog,
    no classifier picking ids.

    Fail-secure: an embedding or search failure is logged and degrades the
    turn to "(lore retrieval failed this turn)" -- never a fabricated document.
    """
    latest = next((m for m in reversed(state.messages) if m.type == "human"), None)
    if latest is None:
        logger.warning("⚠️ [intent_router] no player message to retrieve lore for")
        return "(no lore retrieved this turn)"

    world_name = ctx.campaign.lore_world
    try:
        vector = await embedder.aembed_query(f"{summary}\n{latest.content}")
    except Exception:
        logger.exception("💥 [intent_router] lore query embedding failed")
        return "(lore retrieval failed this turn)"

    world = await asyncio.to_thread(World.get_world_by_name, world_name)
    if world is None:
        logger.warning(f"⚠️ [intent_router] world '{world_name}' not found for lore recall")
        return "(world has no entries yet)"

    try:
        entries = await asyncio.to_thread(LoreEntry.search, world, vector, LORE_TOP_K)
    except Exception:
        logger.exception(f"💥 [intent_router] lore vector search failed for world '{world_name}'")
        return "(lore retrieval failed this turn)"

    if not entries:
        return "(no lore retrieved this turn)"
    titles = ", ".join(f"'{e.title}'" for e in entries)
    logger.info(f"🔍 [intent_router] vector recall hit {len(entries)} lore document(s): {titles}")
    return "\n\n---\n\n".join(f"# {e.title}\n\n{e.content}" for e in entries)


def make_intent_router(ctx: DMContext):
    async def intent_router(state: DungeonMasterState) -> dict:
        """🧭 Classify the player's latest message, then retrieve lore by vector recall."""
        reading = await run_classifier(
            "dm-intent-routing",
            dm_intent_model,
            IntentReading,
            {
                "player_name": ctx.player.name,
                "location": ctx.location,
                "world_clock": ctx.world_clock,
                "active_npcs": ctx.npc_names,
                "player_state": state.player_state,
                "messages": ctx.combined_messages(state, limit=ROUTER_CONTEXT_WINDOW),
            },
            label="intent_router",
        )
        if reading is None:
            logger.error("🧭 Intent classifier failed; continuing without a fabricated reading")
            return {
                "messages": [],
                "intent": None,
                "lore": "(intent classification failed this turn)",
            }
        logger.info(
            f"🧭 Intent: {reading.intent_type} / {reading.scene_mode} "
            f"(adjudicate={reading.needs_adjudication}) -- {reading.summary[:120]}"
        )
        lore = await _retrieve_lore(ctx, state, reading.summary)
        return {"messages": [], "intent": reading, "lore": lore}

    return intent_router


def _cast_issues(state: DungeonMasterState, ctx: DMContext) -> list[str]:
    """🎭 Deterministic cast check: every responding NPC must be in the scene.

    Catches the most common continuity violation (hallucinated NPC names)
    without an LLM call.
    """
    plan = state.plan
    known = {c.name for c in ctx.conversation.characters} | {i.name for i in plan.npcs_to_introduce}
    return [
        f"NPC '{directive.name}' is listed as responding but is not in the active cast; "
        f"remove the directive or introduce the NPC first."
        for directive in plan.responding_npcs
        if directive.name not in known
    ]


def _needs_llm_check(state: DungeonMasterState) -> bool:
    """Whether the plan can violate the LLM-only continuity checks at all.

    Plain-dialogue plans with no introductions, no mechanical state changes,
    no scene change, no secrets, and no adjudication cannot leak secrets,
    ignore dice, or break cast/coherence -- skip the hop.
    """
    plan = state.plan
    return bool(
        plan.npcs_to_introduce
        or plan.participant_state_updates
        or plan.time_location_update
        or plan.secret_notes
        or state.adjudication is not None
    )


def make_continuity_checker(ctx: DMContext):
    async def continuity_checker(state: DungeonMasterState) -> dict:
        """🛡️ Catch contradictions, secret leaks, agency violations, and ignored dice.

        Rejection loops back to the planner exactly once; a turn is never
        hard-failed on continuity grounds. Deterministic gates handle the
        trivial cases so the LLM hop only runs on risky plans.
        """
        if state.plan is None:
            return {"messages": [], "continuity_notes": ""}
        if state.plan_attempts >= MAX_PLAN_ATTEMPTS and state.continuity_notes:
            logger.warning("🛡️ Plan still has continuity issues after repair, proceeding anyway")
            return {"messages": [], "continuity_notes": ""}

        if issues := _cast_issues(state, ctx):
            notes = "\n".join(f"- {issue}" for issue in issues)
            logger.warning(f"🛡️ Plan rejected by deterministic cast check:\n{notes}")
            return {"messages": [], "continuity_notes": notes}

        if not _needs_llm_check(state):
            logger.info("🛡️ Plan is low-risk, skipping LLM continuity check")
            return {"messages": [], "continuity_notes": ""}

        verdict = await run_classifier(
            "dm-continuity-check",
            dm_continuity_model,
            ContinuityVerdict,
            {
                "player_name": ctx.player.name,
                "location": ctx.location,
                "world_clock": ctx.world_clock,
                "active_npcs": ctx.npc_names,
                "player_state": state.player_state,
                "active_npc_states": state.active_npc_states,
                "secret_knowledge": state.secret_knowledge,
                "adjudication": state.adjudication.render() if state.adjudication else "(none this turn)",
                "plan_json": state.plan.model_dump_json(indent=2),
                "messages": ctx.combined_messages(state, limit=CONTINUITY_CONTEXT_WINDOW),
            },
            label="continuity_checker",
        )
        if verdict is None:
            # Fail-secure: do not approve by silence — send the planner back.
            notes = (
                "- Continuity classifier failed to complete; do not assume the plan is safe. "
                "Simplify or re-validate before proceeding."
            )
            logger.error(f"🛡️ Continuity classifier failed; rejecting plan for repair:\n{notes}")
            return {"messages": [], "continuity_notes": notes}

        if verdict.approved or not verdict.issues:
            logger.info("🛡️ Plan approved by continuity checker")
            return {"messages": [], "continuity_notes": ""}

        notes = "\n".join(f"- {issue}" for issue in verdict.issues)
        logger.warning(f"🛡️ Plan rejected by continuity checker:\n{notes}")
        return {"messages": [], "continuity_notes": notes}

    return continuity_checker
