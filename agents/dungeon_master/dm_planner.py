"""DM planner, dice adjudication, and continuity check node."""
import asyncio
from logging import getLogger
from uuid import uuid4

from langchain_core.messages import AIMessage, SystemMessage
from langgraph.graph.state import CompiledStateGraph

from agents.dungeon_master.schemas import Adjudication, ContinuityVerdict, DMContext, DMPlan, run_classifier
from agents.skilled_agent import skill_registry
from contracts.turn_events import DICE_SPEAKER
from hephaestus.agent_architectures import AgentSwarmState, function_to_graph
from tools.dice import resolve_check
from tools.mechanics import list_mechanics, render_mechanics_full
from tools.status_effects import character_sheet_by_id, render_active_status_effects_by_id
from utils.llm_models import dm_continuity_model, dm_planner_model
from utils.prompts import dm_planner_prompt_template

logger = getLogger(__name__)

DEFAULT_DC = 11
MAX_PLAN_ATTEMPTS = 2
CONTINUITY_CONTEXT_WINDOW = 12


def spawn_dm_planner(ctx: DMContext) -> CompiledStateGraph:
    conversation = ctx.conversation
    plan_llm = dm_planner_model.with_structured_output(DMPlan, strict=True)

    async def dm_planner(state: AgentSwarmState) -> dict:
        if ctx.ooc:
            return {"messages": []}
        mechanics_block, effects_block = await asyncio.gather(
            asyncio.to_thread(lambda: render_mechanics_full(list_mechanics(ctx.campaign_id))),
            asyncio.to_thread(
                render_active_status_effects_by_id,
                ctx.player_id,
                conversation.player.name,
                [c.name for c in conversation.characters],
            ),
        )
        skill_body = skill_registry.get("dm-adjudication").body
        if effects_block:
            skill_body += f"\n\n[ACTIVE PERMANENT STATUS EFFECTS]\n{effects_block}"

        npc_descriptions = "\n\n".join(
            f"**{c.name}**:\n{character_sheet_by_id(c.id)}" for c in conversation.characters
        )
        npc_names = ", ".join(c.name for c in conversation.characters) or "(none)"
        continuity_notes = ""
        plan: DMPlan | None = None
        adjudication: Adjudication | None = None

        for attempt in range(1, MAX_PLAN_ATTEMPTS + 1):
            prompt = await dm_planner_prompt_template.ainvoke({
                "messages": ctx.combined_messages(state.messages),
                "lore": ctx.lore,
                "world_events": ctx.world_events,
                "secret_knowledge": ctx.secret_knowledge,
                "open_threads": ctx.open_threads,
                "faction_clocks": ctx.faction_clocks,
                "player_prefs": ctx.player_prefs,
                "contract": conversation.campaign.render_contract(),
                "active_npcs": npc_descriptions,
                "player": ctx.player_sheet,
                "player_state": ctx.player_state,
                "active_npc_states": ctx.active_npc_states,
                "location": ctx.location,
                "world_clock": ctx.world_clock,
                "story_background": ctx.story_background,
                "intent": f"The player's latest move: {ctx.last_human_query(state.messages)}",
                "adjudication": "(pending -- populate plan.adjudication if uncertain and consequential)",
                "continuity_notes": continuity_notes or "(none -- first attempt)",
            })
            if mechanics_block:
                prompt.messages.append(SystemMessage(content=f"[CAMPAIGN MECHANICS]\n{mechanics_block}"))
            prompt.messages.append(SystemMessage(content=skill_body))

            plan = await plan_llm.ainvoke(prompt)
            adjudication = None
            if plan.adjudication is not None:
                ruling = plan.adjudication
                adjudication = Adjudication(**ruling.model_dump())
                if ruling.ruling == "roll":
                    chk = resolve_check(dc=ruling.dc or DEFAULT_DC, advantage=ruling.advantage, modifier=ruling.modifier)
                    adjudication.rolls, adjudication.total, adjudication.outcome = chk.rolls, chk.total, chk.outcome
                else:
                    adjudication.outcome = "success" if ruling.ruling == "auto_success" else "failure"
                plan.action_outcome = (
                    ruling.critical_failure_stakes
                    if adjudication.outcome == "critical_failure" and ruling.critical_failure_stakes
                    else ruling.success_stakes if adjudication.outcome in ("success", "critical_success")
                    else ruling.failure_stakes
                )
                logger.info(f"⚖️ Adjudication:\n{adjudication.render()}")

            risky = bool(
                plan.npcs_to_introduce
                or plan.participant_state_updates
                or plan.time_location_update
                or plan.secret_notes
            )
            if not risky or attempt >= MAX_PLAN_ATTEMPTS:
                break

            verdict = await run_classifier(
                "dm-continuity-check",
                dm_continuity_model,
                ContinuityVerdict,
                {
                    "player_name": conversation.player.name,
                    "location": ctx.location,
                    "world_clock": ctx.world_clock,
                    "active_npcs": npc_names,
                    "player_state": ctx.player_state,
                    "active_npc_states": ctx.active_npc_states,
                    "secret_knowledge": ctx.secret_knowledge,
                    "plan_json": plan.model_dump_json(indent=2),
                    "messages": ctx.combined_messages(state.messages, limit=CONTINUITY_CONTEXT_WINDOW),
                },
                label="continuity_checker",
            )
            if verdict is not None and (verdict.approved or not verdict.issues):
                logger.info("🛡️ Plan approved by continuity checker")
                break
            continuity_notes = (
                "\n".join(f"- {i}" for i in verdict.issues)
                if verdict and verdict.issues
                else "- Continuity classifier failed; simplify and re-validate the plan."
            )
            logger.warning(f"🛡️ Re-planning after continuity check:\n{continuity_notes}")

        ctx.plan = plan
        ctx.adjudication = adjudication
        if adjudication and adjudication.rolls:
            line = adjudication.render_roll_line(conversation.player.name)
            mid = str(uuid4())
            await ctx.sink.stream_start(mid, DICE_SPEAKER)
            await ctx.sink.stream_token(mid, line)
            await ctx.sink.stream_end(mid, line)
            logger.info(f"🎲 Announcing roll: {line}")
            return {"messages": [AIMessage(content=line, name=DICE_SPEAKER, id=mid)]}
        return {"messages": []}

    return function_to_graph(dm_planner, name="dm_planner")
