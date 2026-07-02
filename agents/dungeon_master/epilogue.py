"""Turn epilogue: fire-and-forget scene memory and offscreen faction simulation.

Nothing here blocks the player's turn -- the node snapshots what it needs,
schedules background work, and returns immediately.
"""
from logging import getLogger

from langchain_core.messages import AnyMessage
from pydantic import BaseModel, Field

from agents.dungeon_master.context import DMContext
from agents.dungeon_master.schemas import DMPlan, DungeonMasterState, FactionSimulation, SceneSummary
from database.graphiti_utils import (
    fire_and_forget,
    save_player_preferences,
    save_secret_notes,
    save_world_events,
)
from tools.world_state import (
    advance_faction_clock,
    create_faction_clock,
    list_faction_clocks,
    list_open_threads,
    render_clocks,
    render_threads,
)
from utils.llm_models import dm_faction_model, dm_summarizer_model, scene_change
from utils.prompts import (
    dm_faction_prompt_template,
    dm_scene_summarizer_prompt_template,
    scene_change_prompt_template,
)

logger = getLogger(__name__)

# Ask the scene-change model only after this many turns since the last summary...
MIN_TURNS_BEFORE_CHECK = 4
# ...and summarize unconditionally after this many.
MAX_TURNS_BETWEEN_SUMMARIES = 10
# How many recent messages feed the summarizer and scene-change check.
SCENE_WINDOW = 30


class SceneChanged(BaseModel):
    """Verdict of the scene-change detector."""
    changed: bool = Field(description=(
        "True when the conversation indicates a scene change: time skip, new "
        "location, new setting, or events that clearly end the current scene."))


def _render_transcript(messages: list[AnyMessage]) -> str:
    lines = [f"{m.name or m.type}: {m.content}" for m in messages if m.content]
    return "\n".join(lines[-SCENE_WINDOW:])


def make_turn_epilogue(ctx: DMContext):
    scene_change_llm = scene_change.with_structured_output(SceneChanged, strict=True)
    summarizer_llm = dm_summarizer_model.with_structured_output(SceneSummary, strict=True)
    faction_llm = dm_faction_model.with_structured_output(FactionSimulation, strict=True)

    async def _detect_scene_change(recent: list[AnyMessage]) -> bool:
        prompt = await scene_change_prompt_template.ainvoke({"messages": recent[-SCENE_WINDOW:]})
        verdict: SceneChanged = await scene_change_llm.ainvoke(prompt)
        return verdict.changed

    async def _run_scene_summary(transcript: str) -> None:
        """🧾 Distill the scene into world events and player preferences."""
        prompt = await dm_scene_summarizer_prompt_template.ainvoke({
            "player_name": ctx.player.name,
            "active_npcs": ctx.npc_names,
            "location": ctx.location,
            "world_clock": ctx.world_clock,
            "transcript": transcript,
        })
        summary: SceneSummary = await summarizer_llm.ainvoke(prompt)

        events = [f"Scene summary: {summary.scene_summary}"]
        events.extend(summary.canon_updates)
        events.extend(summary.npc_updates)
        events.extend(f"Unresolved hook: {hook}" for hook in summary.unresolved_hooks)
        await save_world_events(
            events=events, campaign_id=ctx.campaign.id, lore_world=ctx.campaign.lore_world,
        )
        if summary.player_preferences:
            await save_player_preferences(
                notes=summary.player_preferences,
                campaign_id=ctx.campaign.id,
                lore_world=ctx.campaign.lore_world,
            )
        logger.info(
            f"🧾 Scene summarized: {len(summary.canon_updates)} canon update(s), "
            f"{len(summary.unresolved_hooks)} hook(s)"
        )

    async def _run_faction_simulation(turn_summary: str, world_events: str, secrets: str, lore: str) -> None:
        """🌒 Advance offscreen faction agendas in response to the turn."""
        clocks = list_faction_clocks(ctx.campaign.id)
        threads = list_open_threads(ctx.campaign.id)
        prompt = await dm_faction_prompt_template.ainvoke({
            "faction_clocks": render_clocks(clocks),
            "open_threads": render_threads(threads),
            "world_events": world_events,
            "secret_knowledge": secrets,
            "lore": lore,
            "location": ctx.location,
            "world_clock": ctx.world_clock,
            "turn_summary": turn_summary,
        })
        sim: FactionSimulation = await faction_llm.ainvoke(prompt)

        for advance in sim.clock_advances:
            advance_faction_clock(
                ctx.campaign.id, advance.faction, advance.ticks,
                reason=advance.reason, next_move=advance.next_move,
            )
        for new_clock in sim.new_clocks:
            create_faction_clock(
                ctx.campaign.id, new_clock.faction_name, new_clock.goal,
                ticks_max=new_clock.ticks_max, next_move=new_clock.next_move,
            )
        if sim.world_events:
            await save_world_events(
                events=sim.world_events, campaign_id=ctx.campaign.id,
                lore_world=ctx.campaign.lore_world,
            )
        if sim.secret_notes:
            await save_secret_notes(
                notes=sim.secret_notes, campaign_id=ctx.campaign.id,
                lore_world=ctx.campaign.lore_world,
            )
        logger.info(
            f"🌒 Faction simulation: {len(sim.clock_advances)} tick(s), "
            f"{len(sim.new_clocks)} new clock(s), {len(sim.world_events)} event(s)"
        )

    async def _run_epilogue(
        plan: DMPlan,
        recent: list[AnyMessage],
        transcript: str,
        turn_summary: str,
        world_events: str,
        secrets: str,
        lore: str,
        turns_since_summary: int,
    ) -> None:
        scene_ended = bool(plan.time_location_update or plan.world_clock_update)
        if not scene_ended and turns_since_summary >= MAX_TURNS_BETWEEN_SUMMARIES:
            scene_ended = True
            logger.info(f"🧾 {turns_since_summary} turns since last summary, forcing one")
        elif not scene_ended and turns_since_summary >= MIN_TURNS_BEFORE_CHECK:
            try:
                scene_ended = await _detect_scene_change(recent)
            except Exception:
                logger.exception("💥 Scene-change detection failed, skipping summary this turn")

        if scene_ended:
            try:
                await _run_scene_summary(transcript)
                ctx.conversation._turns_since_summary = 0
            except Exception:
                logger.exception("💥 Scene summarizer failed")

        if plan.offscreen_simulation or plan.clock_advances:
            try:
                await _run_faction_simulation(turn_summary, world_events, secrets, lore)
            except Exception:
                logger.exception("💥 Faction simulation failed")

    async def turn_epilogue(state: DungeonMasterState) -> dict:
        """🌙 Schedule post-turn world upkeep without delaying the response."""
        plan = state.plan
        if plan is None:
            return {"messages": []}

        turns_since_summary = getattr(ctx.conversation, "_turns_since_summary", 0) + 1
        ctx.conversation._turns_since_summary = turns_since_summary

        # Snapshot everything now -- persist_messages mutates the buffer next.
        recent = ctx.combined_messages(state, limit=SCENE_WINDOW)
        transcript = _render_transcript(recent)

        summary_bits = [f"Player intent: {state.intent.summary}" if state.intent else ""]
        if state.adjudication and state.adjudication.outcome:
            summary_bits.append(f"Adjudicated outcome: {state.adjudication.outcome}")
        if plan.action_outcome:
            summary_bits.append(f"Action outcome: {plan.action_outcome}")
        summary_bits.extend(f"Event: {e}" for e in plan.new_world_events)
        turn_summary = "\n".join(filter(None, summary_bits)) or "(an ordinary exchange)"

        fire_and_forget(_run_epilogue(
            plan=plan,
            recent=recent,
            transcript=transcript,
            turn_summary=turn_summary,
            world_events=state.world_events,
            secrets=state.secret_knowledge,
            lore=state.lore,
            turns_since_summary=turns_since_summary,
        ))
        return {"messages": []}

    return turn_epilogue
