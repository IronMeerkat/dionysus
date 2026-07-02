"""Continuity checker: validate the DM plan before anything streams to the player."""
from logging import getLogger

from agents.dungeon_master.context import DMContext
from agents.dungeon_master.schemas import ContinuityVerdict, DungeonMasterState
from utils.llm_models import dm_continuity_model
from utils.prompts import dm_continuity_prompt_template

logger = getLogger(__name__)

# First plan + one repaired plan; after that we proceed regardless.
MAX_PLAN_ATTEMPTS = 2
CONTINUITY_CONTEXT_WINDOW = 12


def make_continuity_checker(ctx: DMContext):
    verdict_llm = dm_continuity_model.with_structured_output(ContinuityVerdict, strict=True)

    async def continuity_checker(state: DungeonMasterState) -> dict:
        """🛡️ Catch contradictions, secret leaks, agency violations, and ignored dice.

        Rejection loops back to the planner exactly once; a turn is never
        hard-failed on continuity grounds.
        """
        if state.plan is None:
            return {"messages": [], "continuity_notes": ""}
        if state.plan_attempts >= MAX_PLAN_ATTEMPTS and state.continuity_notes:
            logger.warning("🛡️ Plan still has continuity issues after repair, proceeding anyway")
            return {"messages": [], "continuity_notes": ""}

        prompt = await dm_continuity_prompt_template.ainvoke({
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
        })
        try:
            verdict: ContinuityVerdict = await verdict_llm.ainvoke(prompt)
        except Exception:
            logger.exception("💥 Continuity checker failed, proceeding with unvalidated plan")
            return {"messages": [], "continuity_notes": ""}

        if verdict.approved or not verdict.issues:
            logger.info("🛡️ Plan approved by continuity checker")
            return {"messages": [], "continuity_notes": ""}

        notes = "\n".join(f"- {issue}" for issue in verdict.issues)
        logger.warning(f"🛡️ Plan rejected by continuity checker:\n{notes}")
        return {"messages": [], "continuity_notes": notes}

    return continuity_checker
