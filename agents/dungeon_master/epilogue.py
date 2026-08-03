"""Turn epilogue: fire-and-forget scene memory and offscreen faction simulation.

Nothing here blocks the player's turn -- the node snapshots what it needs,
schedules background work, and returns immediately.
"""
import asyncio
from logging import getLogger

import numpy as np
from langchain_core.messages import AnyMessage

from agents.dungeon_master.classifiers import run_classifier
from agents.dungeon_master.context import DMContext
from agents.dungeon_master.schemas import (
    DMPlan,
    DungeonMasterState,
    FactionSimulation,
    SceneChangeReport,
    SceneEpilogue,
)
from database.models import CharacterMemory, DMSecret, Message, PlayerPreference, WorldEvent
from database.postgres_connection import db_session
from hephaestus.settings import settings
from tools.mechanics import get_mechanic, list_mechanics, render_mechanics_full, upsert_mechanic
from tools.world_state import (
    advance_faction_clock,
    create_faction_clock,
    get_scene_embedding,
    list_faction_clocks,
    list_open_threads,
    render_clocks,
    render_threads,
    set_location,
    set_scene_embedding,
    set_world_clock,
)
from utils.llm_models import dm_faction_model, scene_change
from utils.prompts import dm_faction_prompt_template
from utils.tasks import fire_and_forget

logger = getLogger(__name__)

# Ask the scene-change model only after this many turns since the last summary...
MIN_TURNS_BEFORE_CHECK = 4
# ...and summarize unconditionally after this many.
MAX_TURNS_BETWEEN_SUMMARIES = 10
# How many recent messages feed the summarizer and scene-change check.
SCENE_WINDOW = 30


def _message_centroid(conversation_id: int, limit: int) -> list[float] | None:
    """🧭 Mean of the conversation's most recent embedded message vectors.

    These embeddings already exist on ``messages`` rows from
    ``persist_messages``, so the drift gate costs no embedder calls.
    Returns None when nothing embedded exists yet.
    """
    with db_session() as s:
        rows = (
            s.query(Message.embedding)
            .filter(Message.conversation_id == conversation_id, Message.embedding.isnot(None))
            .order_by(Message.created_at.desc())
            .limit(limit)
            .all()
        )
    if not rows:
        return None
    return np.asarray([row[0] for row in rows], dtype=float).mean(axis=0).tolist()


def make_turn_epilogue(ctx: DMContext):
    faction_llm = dm_faction_model.with_structured_output(FactionSimulation, strict=True)

    async def _run_scene_epilogue(recent: list[AnyMessage], scene_ended: bool) -> SceneEpilogue | None:
        """🧭🧾 One call over the window: scene-change verdict, mechanics
        reconciliation, and (only when the scene ended) scene memory.

        Read the mechanics docs on the worker thread, but pass the snapshot
        campaign_id so no expired ORM attribute is lazily reloaded off the
        event loop's single shared Session.
        """
        mechanics_docs = await asyncio.to_thread(
            lambda: render_mechanics_full(list_mechanics(ctx.campaign_id))
        )
        result = await run_classifier(
            "dm-scene-epilogue",
            scene_change,
            SceneEpilogue,
            {
                "location": ctx.location,
                "world_clock": ctx.world_clock,
                "player_name": ctx.player.name,
                "active_npcs": ctx.npc_names,
                "mechanics_docs": mechanics_docs or "(no negotiated mechanics documents)",
                "scene_ended": (
                    "The scene has DEFINITELY ended (the DM moved time/location or the summary "
                    "cadence forced it): set changed=true and fill every scene-memory field."
                    if scene_ended else
                    "Decide whether the scene ended; fill the scene-memory fields only when "
                    "changed is true."
                ),
                "messages": recent[-SCENE_WINDOW:],
            },
            label="scene_epilogue",
        )
        if result is not None:
            logger.info(
                f"🧭 Scene epilogue: changed={result.changed}, "
                f"{len(result.mechanics_updates)} mechanics update(s), "
                f"{len(result.character_memories)} character memor(ies) -- {result.reason[:120]}"
            )
        return result

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

    async def _scene_drift() -> float | None:
        """🧭 L2 distance between the current window's message-embedding
        centroid and the stored scene centroid.

        None means the gate cannot decide (no stored centroid yet, no
        embedded messages, or a failure) -- the caller then runs the LLM
        scene-change check as today. Distances are always logged so
        ``tau_drift`` can be calibrated against real play.
        """
        try:
            stored, current = await asyncio.gather(
                asyncio.to_thread(get_scene_embedding, ctx.campaign_id),
                asyncio.to_thread(_message_centroid, ctx.conversation.id, SCENE_WINDOW),
            )
        except Exception:
            logger.exception("💥 Scene drift computation failed; gate open")
            return None
        if stored is None or current is None:
            logger.info("🧭 Scene drift unknown (no stored centroid or no embedded messages); gate open")
            return None
        drift = float(np.linalg.norm(np.asarray(stored, dtype=float) - np.asarray(current, dtype=float)))
        logger.info(f"🧭 Scene drift: {drift:.3f} (tau={settings.memory.drift.tau_drift})")
        return drift

    async def _store_scene_centroid() -> None:
        """🧭 Anchor the drift gate to the scene that just got summarized."""
        try:
            centroid = await asyncio.to_thread(_message_centroid, ctx.conversation.id, SCENE_WINDOW)
            if centroid is None:
                logger.warning("⚠️ No embedded messages to centroid; scene embedding left unset")
                return
            await asyncio.to_thread(set_scene_embedding, ctx.campaign_id, centroid)
        except Exception:
            logger.exception("💥 Failed to store the scene embedding centroid")

    async def _persist_scene_memory(result: SceneEpilogue) -> None:
        """🧾 Persist the distilled scene: world events, player preferences,
        per-character memories, and the drift-gate centroid anchor.

        Per-character memories resolve their character_id from the scene
        roster by name; unknown names are logged and skipped.
        """
        events = [f"Scene summary: {result.scene_summary}"]
        events.extend(result.canon_updates)
        events.extend(result.npc_updates)
        events.extend(f"Unresolved hook: {hook}" for hook in result.unresolved_hooks)
        await WorldEvent.add_items(ctx.campaign_id, events)
        if result.player_preferences:
            await PlayerPreference.add_items(ctx.campaign_id, [result.player_preferences])

        ids_by_name = {c.name: c.id for c in ctx.conversation.characters}
        for item in result.character_memories:
            character_id = ids_by_name.get(item.character_name)
            if character_id is None:
                logger.warning(f"⚠️ Scene memory names unknown character '{item.character_name}', skipping")
                continue
            try:
                await asyncio.to_thread(
                    CharacterMemory.add_memory, ctx.campaign_id, character_id, item.title, item.content
                )
            except Exception:
                logger.exception(f"💥 Failed to save scene memory for '{item.character_name}'")

        await _store_scene_centroid()
        logger.info(
            f"🧾 Scene summarized: {len(result.canon_updates)} canon update(s), "
            f"{len(result.unresolved_hooks)} hook(s), {len(result.character_memories)} character memor(ies)"
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

        # The merged scene epilogue runs when the scene ended (memory +
        # reconciliation in one call) or when the DM flagged mechanics
        # movement / the summary cadence wants a verdict -- never on
        # ordinary turns. The cadence trigger is further gated by embedding
        # drift: when the current window's centroid barely moved from the
        # last summarized scene, the call would almost certainly return
        # changed=false, so it is skipped. The mechanics_moved trigger
        # always bypasses the gate (the DM explicitly flagged movement).
        decide = plan.mechanics_moved or (not scene_ended and turns_since_summary >= MIN_TURNS_BEFORE_CHECK)
        if decide and not plan.mechanics_moved:
            drift = await _scene_drift()
            tau = settings.memory.drift.tau_drift
            if drift is not None and drift < tau:
                logger.info(f"🧭 Scene drift {drift:.3f} < tau={tau}; skipping the scene epilogue LLM call")
                decide = False

        if scene_ended or decide:
            try:
                result = await _run_scene_epilogue(recent, scene_ended)
            except Exception:
                logger.exception("💥 Scene epilogue failed, skipping its updates this turn")
                result = None
            if result is not None:
                await _apply_scene_change_report(result)
                if scene_ended or result.changed:
                    if result.scene_summary:
                        await _persist_scene_memory(result)
                        ctx.conversation._turns_since_summary = 0
                    else:
                        logger.warning("⚠️ Scene ended but the epilogue distilled no summary; memory skipped")

        # plan.clock_advances were already applied by the canon manager; the
        # faction sim only runs for turns loud enough to move the offscreen
        # world.
        if plan.offscreen_simulation:
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

        latest = next((m for m in reversed(recent) if m.type == "human"), None)
        summary_bits = [f"Player: {latest.content[:200]}" if latest else ""]
        if state.adjudication and state.adjudication.outcome:
            summary_bits.append(f"Adjudicated outcome: {state.adjudication.outcome}")
        if plan.action_outcome:
            summary_bits.append(f"Action outcome: {plan.action_outcome}")
        summary_bits.extend(f"Event: {e}" for e in plan.new_world_events)
        turn_summary = "\n".join(filter(None, summary_bits)) or "(an ordinary exchange)"

        fire_and_forget(_run_epilogue(
            plan=plan,
            recent=recent,
            turn_summary=turn_summary,
            world_events=state.world_events,
            secrets=state.secret_knowledge,
            lore=state.lore,
            turns_since_summary=turns_since_summary,
        ))
        return {"messages": []}

    return turn_epilogue
