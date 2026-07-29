"""Canon manager: the narrator decorates, but THIS decides what became true."""
import asyncio
from logging import getLogger
from uuid import UUID, uuid4

from langchain_core.messages import HumanMessage

from agents.dungeon_master.context import DMContext
from agents.dungeon_master.schemas import DungeonMasterState
from database.knowledge import save_stream_items
from database.models import DMSecret, WorldEvent
from tools.participants import apply_participant_state_update
from tools.world_state import advance_faction_clock, apply_thread_update, set_location, set_world_clock
from utils.tasks import fire_and_forget

logger = getLogger(__name__)


def make_canon_manager(ctx: DMContext):
    async def canon_manager(state: DungeonMasterState) -> dict:
        """📖 Apply the plan's structured updates through deterministic writes
        to Postgres: world events and secrets; location, world clock, quest
        threads, and faction clocks."""
        plan = state.plan
        if not plan:
            return {"messages": []}

        if plan.new_world_events:
            fire_and_forget(save_stream_items(WorldEvent, ctx.campaign.id, plan.new_world_events))
        if plan.secret_notes:
            fire_and_forget(save_stream_items(DMSecret, ctx.campaign.id, [plan.secret_notes]))
        if plan.time_location_update:
            await asyncio.to_thread(set_location, ctx.campaign.id, plan.time_location_update)
        if plan.world_clock_update:
            await asyncio.to_thread(set_world_clock, ctx.campaign.id, plan.world_clock_update)

        # The three independent write loops run concurrently off the event
        # loop. Each loop only catches/logs its own errors so one failure
        # never silently swallows the others.
        def _apply_threads() -> None:
            for update in plan.thread_updates:
                try:
                    apply_thread_update(ctx.campaign.id, update.title, update.action, update.note)
                except Exception:
                    logger.exception(f"💥 Failed to apply thread update '{update.title}' ({update.action})")

        def _apply_clocks() -> None:
            for advance in plan.clock_advances:
                try:
                    advance_faction_clock(
                        ctx.campaign.id, advance.faction, advance.ticks,
                        reason=advance.reason, next_move=advance.next_move,
                    )
                except Exception:
                    logger.exception(f"💥 Failed to advance faction clock '{advance.faction}'")

        def _apply_participants() -> None:
            for update in plan.participant_state_updates:
                try:
                    apply_participant_state_update(
                        ctx.campaign.id,
                        name=update.name,
                        stats_set=update.stats_set,
                        status_added=[s.model_dump(exclude_none=True) for s in update.status_added],
                        status_removed=update.status_removed,
                        modifiers_set=update.modifiers_set,
                        notes=update.notes,
                    )
                except Exception:
                    logger.exception(f"💥 Failed to apply participant state update for '{update.name}'")

        await asyncio.gather(
            asyncio.to_thread(_apply_threads),
            asyncio.to_thread(_apply_clocks),
            asyncio.to_thread(_apply_participants),
        )

        return {"messages": []}

    return canon_manager


def make_persist_messages(ctx: DMContext):
    async def persist_messages(state: DungeonMasterState) -> dict:
        """Write all messages from this turn to the DB and message buffer."""
        for message in state.messages:
            message.id = message.id or str(uuid4())
            if isinstance(message, HumanMessage):
                message.name = ctx.player.name
            ctx.conversation.add_message(message.type, message.content, message.name, _id=UUID(message.id))

        ctx.conversation.message_buffer.extend(state.messages)
        ids = [m.id for m in ctx.conversation.message_buffer]
        if (dupes := len(ids) - len(set(ids))):
            logger.error(f"👯‍♀️ {dupes} duplicate message IDs detected")

        return {"messages": []}

    return persist_messages
