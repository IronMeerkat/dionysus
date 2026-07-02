"""Rules referee: adjudicate uncertain actions, then let deterministic dice decide."""
from logging import getLogger

from agents.dungeon_master.context import DMContext
from agents.dungeon_master.schemas import Adjudication, AdjudicationRuling, DungeonMasterState
from tools.dice import resolve_check
from utils.llm_models import dm_referee_model
from utils.prompts import dm_rules_referee_prompt_template

logger = getLogger(__name__)

REFEREE_CONTEXT_WINDOW = 12
DEFAULT_DC = 11


def make_rules_referee(ctx: DMContext):
    ruling_llm = dm_referee_model.with_structured_output(AdjudicationRuling, strict=True)

    async def rules_referee(state: DungeonMasterState) -> dict:
        """⚖️ Rule on the player's attempted action and resolve dice when needed.

        The LLM only sets up the situation (ruling, DC, stakes); the dice module
        rolls deterministically. The resulting outcome is canon for the planner.
        """
        intent = state.intent
        if intent is None or not intent.needs_adjudication:
            return {"messages": [], "adjudication": None}

        prompt = await dm_rules_referee_prompt_template.ainvoke({
            "contract": ctx.campaign.render_contract(),
            "player": ctx.player.description,
            "player_state": state.player_state,
            "location": ctx.location,
            "world_clock": ctx.world_clock,
            "lore": state.lore,
            "intent_summary": intent.summary,
            "messages": ctx.combined_messages(state, limit=REFEREE_CONTEXT_WINDOW),
        })
        try:
            ruling: AdjudicationRuling = await ruling_llm.ainvoke(prompt)
        except Exception:
            logger.exception("💥 Rules referee failed, proceeding without adjudication")
            return {"messages": [], "adjudication": None}

        adjudication = Adjudication(**ruling.model_dump())
        if ruling.ruling == "roll":
            check = resolve_check(dc=ruling.dc or DEFAULT_DC, advantage=ruling.advantage)
            adjudication.rolls = check.rolls
            adjudication.total = check.total
            adjudication.outcome = check.outcome
        elif ruling.ruling == "auto_success":
            adjudication.outcome = "success"
        else:  # auto_failure | impossible
            adjudication.outcome = "failure"

        logger.info(f"⚖️ Adjudication:\n{adjudication.render()}")
        return {"messages": [], "adjudication": adjudication}

    return rules_referee
