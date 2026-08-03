"""🎯 Skill-driven classifiers: one helper + the DM's cheap structured hops
(continuity checking, scene epilogue).

Each classifier's instructions live in a SKILL.md file (see ``skills/``);
this module owns only prompt assembly, the structured-output call, and
fail-secure recovery (catch → log → return None / go back — never invent success).
"""
from logging import getLogger
from typing import Any, TypeVar

from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel

from agents.dungeon_master.context import DMContext
from agents.dungeon_master.schemas import ContinuityVerdict, DungeonMasterState
from agents.skills.registry import skill_registry
from utils.llm_models import dm_continuity_model

logger = getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# First plan + one repaired plan; after that we proceed regardless.
MAX_PLAN_ATTEMPTS = 2
# How much recent conversation the continuity hop gets to see.
CONTINUITY_CONTEXT_WINDOW = 12


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


def _drop_unknown_cast(plan, ctx: DMContext) -> list[str]:
    """🎭 Deterministic cast check: drop directives for NPCs not in the scene.

    Catches the most common continuity violation (hallucinated NPC names)
    without an LLM call -- and repairs it surgically instead of sending the
    whole plan back for a costly re-plan.
    """
    known = {c.name for c in ctx.conversation.characters} | {i.name for i in plan.npcs_to_introduce}
    dropped = [d.name for d in plan.responding_npcs if d.name not in known]
    if dropped:
        plan.responding_npcs = [d for d in plan.responding_npcs if d.name in known]
    return dropped


def _needs_llm_check(state: DungeonMasterState) -> bool:
    """Whether the plan can violate the LLM-only continuity checks at all.

    Plain-dialogue plans with no introductions, no mechanical state changes,
    no scene change, and no secrets cannot leak secrets or break cast,
    agency, or coherence -- skip the hop. Dice respect needs no check:
    ``_resolve_adjudication`` resolves the outcome into the plan in code.
    """
    plan = state.plan
    return bool(
        plan.npcs_to_introduce
        or plan.participant_state_updates
        or plan.time_location_update
        or plan.secret_notes
    )


def make_continuity_checker(ctx: DMContext):
    async def continuity_checker(state: DungeonMasterState) -> dict:
        """🛡️ Catch contradictions, secret leaks, and agency violations.

        Rejection loops back to the planner exactly once; a turn is never
        hard-failed on continuity grounds. Deterministic gates handle the
        trivial cases so the LLM hop only runs on risky plans.
        """
        plan = state.plan
        if plan is None:
            return {"messages": [], "continuity_notes": ""}
        if state.plan_attempts >= MAX_PLAN_ATTEMPTS and state.continuity_notes:
            logger.warning("🛡️ Plan still has continuity issues after repair, proceeding anyway")
            return {"messages": [], "continuity_notes": ""}

        update = {"messages": [], "continuity_notes": ""}
        if dropped := _drop_unknown_cast(plan, ctx):
            logger.warning(f"🛡️ Dropped directive(s) for NPCs not in the scene: {', '.join(dropped)}")
            update["plan"] = plan
            has_content = bool(
                plan.responding_npcs or plan.npcs_to_introduce
                or plan.opening_narration or plan.closing_narration or plan.action_outcome
            )
            if not has_content:
                notes = (
                    "- Every responding NPC was unknown to the scene, so their directives were "
                    "removed and nothing is left of the turn. Re-plan without them."
                )
                logger.warning(f"🛡️ Plan gutted by cast repair; sending back for re-plan:\n{notes}")
                return {**update, "continuity_notes": notes}

        if not _needs_llm_check(state):
            logger.info("🛡️ Plan is low-risk, skipping LLM continuity check")
            return update

        variables = {
            "player_name": ctx.player.name,
            "location": ctx.location,
            "world_clock": ctx.world_clock,
            "active_npcs": ctx.npc_names,
            "player_state": state.player_state,
            "active_npc_states": state.active_npc_states,
            "secret_knowledge": state.secret_knowledge,
            "plan_json": plan.model_dump_json(indent=2),
            "messages": ctx.combined_messages(state, limit=CONTINUITY_CONTEXT_WINDOW),
        }
        verdict = await run_classifier(
            "dm-continuity-check", dm_continuity_model, ContinuityVerdict, variables,
            label="continuity_checker",
        )
        if verdict is None:
            # A classifier flake must not cost a planner re-run -- retry once first.
            verdict = await run_classifier(
                "dm-continuity-check", dm_continuity_model, ContinuityVerdict, variables,
                label="continuity_checker(retry)",
            )
        if verdict is None:
            # Fail-secure: do not approve by silence — send the planner back.
            notes = (
                "- Continuity classifier failed to complete; do not assume the plan is safe. "
                "Simplify or re-validate before proceeding."
            )
            logger.error(f"🛡️ Continuity classifier failed twice; rejecting plan for repair:\n{notes}")
            return {**update, "continuity_notes": notes}

        if verdict.approved or not verdict.issues:
            logger.info("🛡️ Plan approved by continuity checker")
            return update

        notes = "\n".join(f"- {issue}" for issue in verdict.issues)
        logger.warning(f"🛡️ Plan rejected by continuity checker:\n{notes}")
        return {**update, "continuity_notes": notes}

    return continuity_checker
