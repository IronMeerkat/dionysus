"""The DM brain: produce a structured plan for the turn, adjudication included."""
import asyncio
from logging import getLogger
from uuid import uuid4

from langchain_core.messages import AIMessage, SystemMessage

from agents.dungeon_master.context import DMContext
from agents.dungeon_master.schemas import Adjudication, DMPlan, DungeonMasterState
from agents.skills.registry import skill_registry
from tools.dice import resolve_check
from tools.mechanics import list_mechanics, render_mechanics_full
from tools.status_effects import render_active_status_effects_by_id
from utils.llm_models import dm_planner_model
from utils.prompts import dm_planner_prompt_template

logger = getLogger(__name__)

DEFAULT_DC = 11


def _resolve_adjudication(plan: DMPlan) -> Adjudication | None:
    """🎲 Turn the plan's ruling into a canon outcome with deterministic dice.

    The planner only sets up the situation (ruling, DC, stakes); the dice
    module rolls. The ruling's stakes become the plan's action_outcome, so
    downstream nodes (narrator, continuity checker, epilogue) see exactly the
    same state shape the old rules_referee -> planner chain produced.
    """
    ruling = plan.adjudication
    if ruling is None:
        return None

    adjudication = Adjudication(**ruling.model_dump())
    if ruling.ruling == "roll":
        check = resolve_check(
            dc=ruling.dc or DEFAULT_DC,
            advantage=ruling.advantage,
            modifier=ruling.modifier,
        )
        adjudication.rolls = check.rolls
        adjudication.total = check.total
        adjudication.outcome = check.outcome
    elif ruling.ruling == "auto_success":
        adjudication.outcome = "success"
    else:  # auto_failure | impossible
        adjudication.outcome = "failure"

    if adjudication.outcome == "critical_failure" and ruling.critical_failure_stakes:
        plan.action_outcome = ruling.critical_failure_stakes
    elif adjudication.outcome in ("success", "critical_success"):
        plan.action_outcome = ruling.success_stakes
    else:
        plan.action_outcome = ruling.failure_stakes

    logger.info(f"⚖️ Adjudication:\n{adjudication.render()}")
    return adjudication


def make_dm_planner(ctx: DMContext):
    plan_llm = dm_planner_model.with_structured_output(DMPlan, strict=True)

    async def dm_planner(state: DungeonMasterState) -> dict:
        """🧠 Decide what happens this turn, honoring intent and adjudicating actions."""
        intent_block = state.intent.render() if state.intent else "(no intent reading)"
        needs_adjudication = bool(state.intent and state.intent.needs_adjudication)
        adjudication_block = (
            "(pending -- you rule on the action via the plan's adjudication field; "
            "code rolls the dice and resolves the outcome after your ruling)"
            if needs_adjudication
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
            "player": ctx.player_sheet,
            "player_state": state.player_state,
            "active_npc_states": state.active_npc_states,
            "location": ctx.location,
            "world_clock": ctx.world_clock,
            "story_background": ctx.story_background,
            "intent": intent_block,
            "adjudication": adjudication_block,
            "continuity_notes": continuity_block,
        })

        # Negotiated campaign mechanics are binding procedures for the plan;
        # appended (not templated) so the Langfuse prompt stays stable and
        # campaigns without mechanics pay no prompt cost. The mechanics query
        # runs on a worker thread but takes the snapshot campaign_id, so no
        # expired ORM attribute is lazily reloaded off the event loop.
        mechanics_block = await asyncio.to_thread(
            lambda: render_mechanics_full(list_mechanics(ctx.campaign_id))
        )
        if mechanics_block:
            logger.info(
                f"⚙️ Injecting campaign mechanics ({len(mechanics_block)} chars) into the planner prompt"
            )
            prompt.messages.append(SystemMessage(content=(
                "[CAMPAIGN MECHANICS]\n"
                "The following custom mechanics were negotiated for this campaign. "
                "They are binding procedures, not suggestions -- plan NPC behavior, "
                "rulings, and outcomes around them. When this turn's events move "
                "tracked state in one of these documents (a spike, a clamped rung, "
                "a recovery move, a boundary their rules key off), set the plan's "
                "mechanics_moved flag -- the scene-change updater revises the "
                "documents after the turn.\n\n"
                f"{mechanics_block}"
            )))

        if needs_adjudication:
            # The dm-adjudication skill's instructions apply only this turn;
            # the planner prompt already carries the contract, player state,
            # lore, and intent summary the ruling needs. The PC's permanent
            # sheet effects are filtered deterministically by scene presence
            # (negated effects are hidden) and appended to the skill body.
            # present_names and the player id/name are captured on the event
            # loop; the effect query/render runs on the worker thread via
            # the by-id helper so no expired ORM relationship is touched
            # off-loop.
            present_names = [c.name for c in ctx.conversation.characters]
            player_id = ctx.player_id
            player_name = ctx.player.name
            effects_block = await asyncio.to_thread(
                render_active_status_effects_by_id, player_id, player_name, present_names
            )
            skill_body = skill_registry.get("dm-adjudication").body
            if effects_block:
                skill_body += f"\n\n[ACTIVE PERMANENT STATUS EFFECTS]\n{effects_block}"
            else:
                logger.info("🧬 No active permanent status effects for the PC this turn")
            prompt.messages.append(SystemMessage(content=skill_body))

        plan: DMPlan = await plan_llm.ainvoke(prompt)
        adjudication = _resolve_adjudication(plan) if needs_adjudication else None
        if not needs_adjudication and plan.adjudication is not None:
            logger.warning("⚖️ Planner ruled on an action that needed no adjudication; discarding ruling")
            plan.adjudication = None
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
            "adjudication": adjudication,
            "build_queue": list(plan.npcs_to_introduce),
            "plan_attempts": state.plan_attempts + 1,
        }

    return dm_planner


def make_roll_announcer(ctx: DMContext):
    async def roll_announcer(state: DungeonMasterState) -> dict:
        """🎲 Announce the resolved check as a compact chat line.

        Runs only after the plan is final (continuity approved), so dice
        re-rolled during a repair pass stay silent. Emits nothing when the
        turn had no roll. The message lands before narration and NPC
        responses, so the player sees the roll and then its consequences.
        The line streams straight to the socket with the same id the message
        is persisted under, matching the NPC executor's bubble flow.
        """
        adjudication = state.adjudication
        if not adjudication or not adjudication.rolls:
            return {"messages": []}
        line = adjudication.render_roll_line(ctx.player.name)
        message_id = str(uuid4())
        if ctx.sio is not None and ctx.sid is not None:
            await ctx.sio.emit("stream_start", {"messageId": message_id, "name": "Dice"}, to=ctx.sid)
            await ctx.sio.emit("stream_token", {"messageId": message_id, "token": line}, to=ctx.sid)
            await ctx.sio.emit("stream_end", {"messageId": message_id, "content": line}, to=ctx.sid)
        logger.info(f"🎲 Announcing roll: {line}")
        return {"messages": [AIMessage(content=line, name="Dice", id=message_id)]}

    return roll_announcer
