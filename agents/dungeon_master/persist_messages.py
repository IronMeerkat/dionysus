"""Message persistence, canon updates, scene epilogue, and faction simulation node."""
import asyncio
from logging import getLogger
from uuid import UUID, uuid4

import numpy as np
from langchain_core.messages import AnyMessage, HumanMessage
from langgraph.graph.state import CompiledStateGraph

from agents.dungeon_master.schemas import (
    DMContext,
    DMPlan,
    FactionSimulation,
    SceneEpilogue,
    run_classifier,
)
from database.models import CharacterMemory, DMSecret, Message, PlayerPreference, WorldEvent
from database.postgres_connection import db_session
from database.session_utils import embedder
from hephaestus.agent_architectures import AgentSwarmState, function_to_graph
from hephaestus.settings import settings
from tools.mechanics import get_mechanic, list_mechanics, render_mechanics_full, upsert_mechanic
from tools.participants import apply_participant_state_update
from tools.world_state import (
    advance_faction_clock,
    apply_thread_update,
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

MIN_TURNS_BEFORE_CHECK = 4
MAX_TURNS_BETWEEN_SUMMARIES = 10
SCENE_WINDOW = 30


async def _run_epilogue(
    ctx: DMContext, plan: DMPlan, recent: list[AnyMessage], turn_summary: str, turns_since_summary: int
) -> None:
    """🌙 Background post-turn scene memory, mechanics reconciliation, and faction simulation."""
    def _centroid() -> list[float] | None:
        with db_session() as s:
            rows = (
                s.query(Message.embedding)
                .filter(Message.conversation_id == ctx.conversation.id, Message.embedding.isnot(None))
                .order_by(Message.created_at.desc())
                .limit(SCENE_WINDOW)
                .all()
            )
        return np.asarray([r[0] for r in rows], dtype=float).mean(axis=0).tolist() if rows else None

    scene_ended = bool(plan.time_location_update or plan.world_clock_update) or (
        turns_since_summary >= MAX_TURNS_BETWEEN_SUMMARIES
    )
    decide = plan.mechanics_moved or (not scene_ended and turns_since_summary >= MIN_TURNS_BEFORE_CHECK)
    if decide and not plan.mechanics_moved:
        try:
            stored, current = await asyncio.gather(
                asyncio.to_thread(get_scene_embedding, ctx.campaign_id),
                asyncio.to_thread(_centroid),
            )
            if stored is not None and current is not None:
                drift = float(np.linalg.norm(np.asarray(stored, dtype=float) - np.asarray(current, dtype=float)))
                logger.info(f"🧭 Scene drift: {drift:.3f} (tau={settings.memory.drift.tau_drift})")
                if drift < settings.memory.drift.tau_drift:
                    decide = False
        except Exception:
            logger.exception("💥 Scene drift computation failed; gate open")

    if scene_ended or decide:
        mechanics_docs = await asyncio.to_thread(lambda: render_mechanics_full(list_mechanics(ctx.campaign_id)))
        result = await run_classifier(
            "dm-scene-epilogue",
            scene_change,
            SceneEpilogue,
            {
                "location": ctx.location,
                "world_clock": ctx.world_clock,
                "player_name": ctx.conversation.player.name,
                "active_npcs": ", ".join(c.name for c in ctx.conversation.characters) or "(none)",
                "mechanics_docs": mechanics_docs or "(no negotiated mechanics documents)",
                "scene_ended": (
                    "The scene has DEFINITELY ended: set changed=true and fill every scene-memory field."
                    if scene_ended else
                    "Decide whether the scene ended; fill scene-memory fields only when changed is true."
                ),
                "messages": recent[-SCENE_WINDOW:],
            },
            label="scene_epilogue",
        )
        if result is not None:
            if result.location:
                try:
                    await asyncio.to_thread(set_location, ctx.campaign_id, result.location)
                except Exception:
                    logger.exception(f"💥 Failed to apply scene-change location '{result.location}'")
            if result.world_clock:
                try:
                    await asyncio.to_thread(set_world_clock, ctx.campaign_id, result.world_clock)
                except Exception:
                    logger.exception(f"💥 Failed to apply scene-change world clock '{result.world_clock}'")
            for upd in result.mechanics_updates:
                try:
                    if await asyncio.to_thread(get_mechanic, ctx.campaign_id, upd.title) is not None:
                        await asyncio.to_thread(upsert_mechanic, ctx.campaign_id, upd.title, upd.content)
                except Exception:
                    logger.exception(f"💥 Failed to update mechanics doc '{upd.title}'")

            if (scene_ended or result.changed) and result.scene_summary:
                events = [
                    f"Scene summary: {result.scene_summary}",
                    *result.canon_updates,
                    *result.npc_updates,
                    *(f"Unresolved hook: {h}" for h in result.unresolved_hooks),
                ]
                await WorldEvent.add_items(ctx.campaign_id, events)
                if result.player_preferences:
                    await PlayerPreference.add_items(ctx.campaign_id, [result.player_preferences])
                ids_by_name = {c.name: c.id for c in ctx.conversation.characters}
                for item in result.character_memories:
                    if (cid := ids_by_name.get(item.character_name)) is not None:
                        try:
                            await asyncio.to_thread(
                                CharacterMemory.add_memory, ctx.campaign_id, cid, item.title, item.content
                            )
                        except Exception:
                            logger.exception(f"💥 Failed to save scene memory for '{item.character_name}'")
                try:
                    if (c_vec := await asyncio.to_thread(_centroid)) is not None:
                        await asyncio.to_thread(set_scene_embedding, ctx.campaign_id, c_vec)
                except Exception:
                    logger.exception("💥 Failed to store scene embedding centroid")
                ctx.conversation._turns_since_summary = 0
                logger.info(f"🧾 Scene summarized: {len(result.canon_updates)} canon update(s)")

    if plan.offscreen_simulation:
        try:
            clocks, threads = list_faction_clocks(ctx.campaign_id), list_open_threads(ctx.campaign_id)
            prompt = await dm_faction_prompt_template.ainvoke({
                "faction_clocks": render_clocks(clocks),
                "open_threads": render_threads(threads),
                "world_events": ctx.world_events,
                "secret_knowledge": ctx.secret_knowledge,
                "lore": ctx.lore,
                "location": ctx.location,
                "world_clock": ctx.world_clock,
                "turn_summary": turn_summary,
            })
            sim: FactionSimulation = await dm_faction_model.with_structured_output(
                FactionSimulation, strict=True
            ).ainvoke(prompt)
            for adv in sim.clock_advances:
                advance_faction_clock(ctx.campaign_id, adv.faction, adv.ticks, reason=adv.reason, next_move=adv.next_move)
            for nc in sim.new_clocks:
                create_faction_clock(ctx.campaign_id, nc.faction_name, nc.goal, ticks_max=nc.ticks_max, next_move=nc.next_move)
            if sim.world_events:
                await WorldEvent.add_items(ctx.campaign_id, sim.world_events)
            if sim.secret_notes:
                await DMSecret.add_items(ctx.campaign_id, [sim.secret_notes])
            logger.info(f"🌒 Faction simulation: {len(sim.clock_advances)} tick(s), {len(sim.new_clocks)} new clock(s)")
        except Exception:
            logger.exception("💥 Faction simulation failed")


def spawn_persist_messages(ctx: DMContext) -> CompiledStateGraph:
    conversation = ctx.conversation

    async def persist_messages(state: AgentSwarmState) -> dict:
        plan = ctx.plan
        if not ctx.ooc and plan:
            cid = ctx.campaign_id
            if plan.new_world_events:
                fire_and_forget(WorldEvent.add_items(cid, plan.new_world_events))
            if plan.secret_notes:
                fire_and_forget(DMSecret.add_items(cid, [plan.secret_notes]))
            if plan.time_location_update:
                ctx.location = plan.time_location_update
                await asyncio.to_thread(set_location, cid, plan.time_location_update)
            if plan.world_clock_update:
                ctx.world_clock = plan.world_clock_update
                await asyncio.to_thread(set_world_clock, cid, plan.world_clock_update)

            def _apply_canon() -> None:
                for u in plan.thread_updates:
                    try:
                        apply_thread_update(cid, u.title, u.action, u.note)
                    except Exception:
                        logger.exception(f"💥 Failed thread update '{u.title}'")
                for a in plan.clock_advances:
                    try:
                        advance_faction_clock(cid, a.faction, a.ticks, reason=a.reason, next_move=a.next_move)
                    except Exception:
                        logger.exception(f"💥 Failed clock advance '{a.faction}'")
                for p in plan.participant_state_updates:
                    try:
                        apply_participant_state_update(
                            cid,
                            name=p.name,
                            stats_set=p.stats_set,
                            status_added=[s.model_dump(exclude_none=True) for s in p.status_added],
                            status_removed=p.status_removed,
                            modifiers_set=p.modifiers_set,
                            notes=p.notes,
                        )
                    except Exception:
                        logger.exception(f"💥 Failed participant state update '{p.name}'")

            await asyncio.to_thread(_apply_canon)

            turns_since = getattr(conversation, "_turns_since_summary", 0) + 1
            conversation._turns_since_summary = turns_since
            recent = ctx.combined_messages(state.messages, limit=SCENE_WINDOW)
            summary_bits = [
                f"Player: {ctx.last_human_query(recent, '')[:200]}",
                f"Adjudicated outcome: {ctx.adjudication.outcome}" if ctx.adjudication and ctx.adjudication.outcome else "",
                f"Action outcome: {plan.action_outcome}" if plan.action_outcome else "",
                *(f"Event: {e}" for e in plan.new_world_events),
            ]
            turn_summary = "\n".join(filter(None, summary_bits)) or "(an ordinary exchange)"
            fire_and_forget(_run_epilogue(ctx, plan, recent, turn_summary, turns_since))

        embeddable = [m for m in state.messages if m.type in ("human", "ai")]
        vectors = await asyncio.gather(
            *(embedder.aembed_query(m.content) for m in embeddable), return_exceptions=True
        )
        vec_by_id = {
            msg.id: (None if isinstance(res, Exception) else res)
            for msg, res in zip(embeddable, vectors)
        }
        for msg, res in zip(embeddable, vectors):
            if isinstance(res, Exception):
                logger.warning(f"⚠️ [persist_messages] embedding failed for {msg.id}: {res}")

        for message in state.messages:
            message.id = message.id or str(uuid4())
            if isinstance(message, HumanMessage):
                message.name = conversation.player.name
            conversation.add_message(
                message.type, message.content, message.name,
                _id=UUID(message.id), embedding=vec_by_id.get(message.id),
            )
        conversation.message_buffer.extend(state.messages)
        return {"messages": []}

    return function_to_graph(persist_messages, name="persist_messages")
