"""Turn epilogue: fire-and-forget scene memory and offscreen faction simulation.

Nothing here blocks the player's turn -- the node snapshots what it needs,
schedules background work, and returns immediately.
"""
import asyncio
from logging import getLogger

from langchain_core.messages import AnyMessage

from agents.dungeon_master.classifiers import run_classifier
from agents.dungeon_master.context import DMContext
from agents.dungeon_master.schemas import (
    DMPlan,
    DungeonMasterState,
    FactionSimulation,
    SceneChangeReport,
    SceneSummary,
)
from database.models import DMSecret, PlayerPreference, WorldEvent
from tools.mechanics import get_mechanic, list_mechanics, render_mechanics_full, upsert_mechanic
from tools.world_state import (
    advance_faction_clock,
    create_faction_clock,
    list_faction_clocks,
    list_open_threads,
    render_clocks,
    render_threads,
    set_location,
    set_world_clock,
)
from utils.llm_models import dm_faction_model, dm_summarizer_model, scene_change
from utils.prompts import (
    dm_faction_prompt_template,
    dm_scene_summarizer_prompt_template,
)
from utils.tasks import fire_and_forget

logger = getLogger(__name__)

# Ask the scene-change model only after this many turns since the last summary...
MIN_TURNS_BEFORE_CHECK = 4
# ...and summarize unconditionally after this many.
MAX_TURNS_BETWEEN_SUMMARIES = 10
# How many recent messages feed the summarizer and scene-change check.
SCENE_WINDOW = 30


def _render_transcript(messages: list[AnyMessage]) -> str:
    lines = [f"{m.name or m.type}: {m.content}" for m in messages if m.content]
    return "\n".join(lines[-SCENE_WINDOW:])


def make_turn_epilogue(ctx: DMContext):
    summarizer_llm = dm_summarizer_model.with_structured_output(SceneSummary, strict=True)
    faction_llm = dm_faction_model.with_structured_output(FactionSimulation, strict=True)

    async def _run_scene_change_check(recent: list[AnyMessage]) -> SceneChangeReport | None:
        """🧭 Ask the scene-change detector for a verdict plus state consequences."""
        # Read the mechanics docs on the worker thread, but pass the snapshot
        # campaign_id so no expired ORM attribute is lazily reloaded off the
        # event loop's single shared Session.
        mechanics_docs = await asyncio.to_thread(
            lambda: render_mechanics_full(list_mechanics(ctx.campaign_id))
        )
        report = await run_classifier(
            "dm-scene-change",
            SceneChangeReport,
            scene_change,
            {
                "location": ctx.location,
                "world_clock": ctx.world_clock,
                "mechanics_docs": mechanics_docs or "(no negotiated mechanics documents)",
                "messages": recent[-SCENE_WINDOW:],
            },
            label="scene_change",
        )
        if report is not None:
            logger.info(
                f"🧭 Scene-change report: changed={report.changed}, "
                f"{len(report.mechanics_updates)} mechanics update(s) -- {report.reason[:120]}"
            )
        return report

    async def _apply_scene_change_report(report: SceneChangeReport) -> None:
        """📌 Persist the detector's state consequences through deterministic writes.

        Mechanics updates are applied only for documents that already exist --
        the detector reconciles negotiated systems, it can never invent new ones.
        """
        if report.location:
            try:
                await asyncio.to_thread(set_location, ctx.campaign_id, report.location)
            except Exception:
                logger.exception(f"💥 Failed to apply scene-change location '{report.location}'")
        if report.world_clock:
            try:
                await asyncio.to_thread(set_world_clock, ctx.campaign_id, report.world_clock)
            except Exception:
                logger.exception(f"💥 Failed to apply scene-change world clock '{report.world_clock}'")
        applied: list[str] = []
        for update in report.mechanics_updates:
            try:
                existing = await asyncio.to_thread(get_mechanic, ctx.campaign_id, update.title)
                if existing is None:
                    logger.warning(
                        f"⚠️ Scene-change updater named unknown mechanics doc "
                        f"'{update.title}', skipping"
                    )
                    continue
                await asyncio.to_thread(upsert_mechanic, ctx.campaign_id, update.title, update.content)
                applied.append(existing.title)
            except Exception:
                logger.exception(f"💥 Failed to update mechanics doc '{update.title}'")
        if applied:
            logger.info(f"⚙️ Scene-change updater revised mechanics doc(s): {', '.join(applied)}")

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
        await WorldEvent.add_items(ctx.campaign_id, events)
        if summary.player_preferences:
            await PlayerPreference.add_items(ctx.campaign_id, [summary.player_preferences])
        logger.info(
            f"🧾 Scene summarized: {len(summary.canon_updates)} canon update(s), "
            f"{len(summary.unresolved_hooks)} hook(s)"
        )

    async def _run_faction_simulation(turn_summary: str, world_events: str, secrets: str, lore: str) -> None:
        """🌒 Advance offscreen faction agendas in response to the turn."""
        clocks = list_faction_clocks(ctx.campaign_id)
        threads = list_open_threads(ctx.campaign_id)
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
                ctx.campaign_id, advance.faction, advance.ticks,
                reason=advance.reason, next_move=advance.next_move,
            )
        for new_clock in sim.new_clocks:
            create_faction_clock(
                ctx.campaign_id, new_clock.faction_name, new_clock.goal,
                ticks_max=new_clock.ticks_max, next_move=new_clock.next_move,
            )
        if sim.world_events:
            await WorldEvent.add_items(ctx.campaign_id, sim.world_events)
        if sim.secret_notes:
            await DMSecret.add_items(ctx.campaign_id, [sim.secret_notes])
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

        # The detector runs only when the DM flagged mechanics movement or the
        # summary cadence wants a verdict -- never on ordinary turns.
        report: SceneChangeReport | None = None
        if plan.mechanics_moved or (not scene_ended and turns_since_summary >= MIN_TURNS_BEFORE_CHECK):
            try:
                report = await _run_scene_change_check(recent)
            except Exception:
                logger.exception("💥 Scene-change detection failed, skipping its updates this turn")
            if report is not None:
                await _apply_scene_change_report(report)

        if not scene_ended and turns_since_summary >= MAX_TURNS_BETWEEN_SUMMARIES:
            scene_ended = True
            logger.info(f"🧾 {turns_since_summary} turns since last summary, forcing one")
        elif not scene_ended and report is not None:
            scene_ended = report.changed

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
