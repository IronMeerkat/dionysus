"""The DM brain: produce a structured plan for the turn."""
from logging import getLogger

from agents.dungeon_master.context import DMContext
from agents.dungeon_master.schemas import DMPlan, DungeonMasterState
from utils.llm_models import dm_planner_model
from utils.prompts import dm_planner_prompt_template

logger = getLogger(__name__)


def make_dm_planner(ctx: DMContext):
    plan_llm = dm_planner_model.with_structured_output(DMPlan, strict=True)

    async def dm_planner(state: DungeonMasterState) -> dict:
        """🧠 Decide what happens this turn, honoring intent and adjudication."""
        intent_block = state.intent.render() if state.intent else "(no intent reading)"
        adjudication_block = (
            state.adjudication.render() if state.adjudication
            else "(no adjudication this turn -- plain dialogue or trivial action)"
        )
        continuity_block = state.continuity_notes or "(none -- first attempt)"
        if state.continuity_notes:
            logger.info(f"🔁 Re-planning (attempt {state.plan_attempts + 1}) with continuity notes")

        prompt = await dm_planner_prompt_template.ainvoke({
            "messages": ctx.combined_messages(state),
            "lore": state.lore,
            "world_events": state.world_events,
            "secret_knowledge": state.secret_knowledge,
            "open_threads": state.open_threads,
            "faction_clocks": state.faction_clocks,
            "player_prefs": state.player_prefs,
            "contract": ctx.campaign.render_contract(),
            "active_npcs": ctx.npc_descriptions,
            "player": ctx.player.description,
            "player_state": state.player_state,
            "active_npc_states": state.active_npc_states,
            "location": ctx.location,
            "world_clock": ctx.world_clock,
            "story_background": ctx.story_background,
            "intent": intent_block,
            "adjudication": adjudication_block,
            "continuity_notes": continuity_block,
        })

        plan: DMPlan = await plan_llm.ainvoke(prompt)
        logger.info(
            f"📝 Plan: {len(plan.responding_npcs)} NPC(s), "
            f"{len(plan.npcs_to_introduce)} intro(s), "
            f"{len(plan.thread_updates)} thread update(s), "
            f"{len(plan.clock_advances)} clock tick(s), "
            f"offscreen={plan.offscreen_simulation}"
        )
        return {
            "messages": [],
            "plan": plan,
            "build_queue": list(plan.npcs_to_introduce),
            "plan_attempts": state.plan_attempts + 1,
        }

    return dm_planner
