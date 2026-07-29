"""Shared turn context and the context-loading nodes for the DM supervisor."""
import asyncio
from dataclasses import dataclass
from logging import getLogger

import socketio
from langchain_core.messages import AnyMessage, HumanMessage

from agents.dungeon_master.schemas import DungeonMasterState
from agents.skills.registry import _load_lore_context
from database.knowledge import load_recent_stream
from database.models import DMSecret, PlayerPreference, WorldEvent
from database.models.conversation import Conversation
from tools.mechanics import list_mechanics, render_mechanics_full
from tools.participants import render_participant_state, render_participant_states
from tools.status_effects import character_sheet
from tools.world_state import (
    list_faction_clocks,
    list_open_threads,
    render_clocks,
    render_threads,
)

logger = getLogger(__name__)


@dataclass
class DMContext:
    """Everything a DM node needs about the session it is running in."""
    conversation: Conversation
    sio: socketio.AsyncServer | None = None
    sid: str | None = None

    @property
    def campaign(self):
        return self.conversation.campaign

    @property
    def player(self):
        return self.conversation.player

    @property
    def world_clock(self) -> str:
        return self.campaign.world_clock or "(unspecified)"

    @property
    def location(self) -> str:
        return self.campaign.location

    @property
    def story_background(self) -> str:
        return self.campaign.story_background or ""

    @property
    def mechanics(self) -> str:
        """⚙️ The campaign's negotiated mechanics documents, in full markdown.

        Queries Postgres, so call sites on the event loop should wrap it in
        ``asyncio.to_thread``. Empty string when nothing was negotiated.
        """
        return render_mechanics_full(list_mechanics(self.campaign.id))

    @property
    def npc_names(self) -> str:
        names = [c.name for c in self.conversation.characters]
        return ", ".join(names) if names else "(none)"

    @property
    def npc_descriptions(self) -> str:
        return "\n\n".join(f"**{c.name}**:\n{character_sheet(c)}" for c in self.conversation.characters)

    @property
    def player_sheet(self) -> str:
        """The PC's character card with permanent status effects appended."""
        return character_sheet(self.player)

    def combined_messages(self, state: DungeonMasterState, limit: int | None = None) -> list[AnyMessage]:
        combo = [*self.conversation.message_buffer, *state.messages]
        if limit is not None:
            combo = combo[-min(limit, len(combo)):]
        return combo

    @staticmethod
    def last_human_query(state: DungeonMasterState, fallback: str = "general scene") -> str:
        last_human = next((m for m in reversed(state.messages) if isinstance(m, HumanMessage)), None)
        return last_human.content if last_human else fallback


def make_state_loader(ctx: DMContext):
    async def state_loader(state: DungeonMasterState) -> dict:
        """🗄️ Load structured world state from Postgres: quest threads, faction
        clocks, participant mechanical state, and the recent world events,
        DM secrets, and player preference streams.

        Cheap, so it runs first -- the intent router only needs player_state,
        which lets the slower lore-retriever tool loop overlap with intent
        classification.
        """
        # The participant renders share the codebase's one global Session and
        # can commit (ensure_campaign_participant), so they run sequentially
        # on a single thread; everything else uses per-call sessions and is
        # safe to gather. The PC is excluded from the NPC roster in case it
        # was also added to the conversation's character list.
        def _participant_states() -> tuple[str, str]:
            npcs = [c for c in ctx.conversation.characters if c.id != ctx.player.id]
            return (
                render_participant_state(ctx.campaign.id, ctx.player.id),
                render_participant_states(ctx.campaign.id, npcs),
            )

        (threads_rows, clocks_rows, (player_state, npc_states),
         events, secrets, prefs, lore_catalog) = await asyncio.gather(
            asyncio.to_thread(list_open_threads, ctx.campaign.id),
            asyncio.to_thread(list_faction_clocks, ctx.campaign.id),
            asyncio.to_thread(_participant_states),
            asyncio.to_thread(load_recent_stream, WorldEvent, ctx.campaign.id),
            asyncio.to_thread(load_recent_stream, DMSecret, ctx.campaign.id),
            asyncio.to_thread(load_recent_stream, PlayerPreference, ctx.campaign.id),
            _load_lore_context([], world_name=ctx.campaign.lore_world),
        )
        threads = render_threads(threads_rows)
        clocks = render_clocks(clocks_rows)

        logger.info(
            f"🗄️ World state loaded: {len(threads.splitlines())} threads, "
            f"{len(clocks.splitlines())} clocks, "
            f"{len(events.splitlines())} events, {len(secrets.splitlines())} secrets, "
            f"{len(prefs.splitlines())} prefs, "
            f"{len(player_state.splitlines())} player-state, "
            f"{len(npc_states.splitlines())} npc-state lines, "
            f"{len(lore_catalog.splitlines())} lore-catalog lines"
        )
        return {
            "messages": [],
            "open_threads": threads,
            "faction_clocks": clocks,
            "player_state": player_state,
            "active_npc_states": npc_states,
            "world_events": events,
            "secret_knowledge": secrets,
            "player_prefs": prefs or "(nothing learned yet)",
            "lore_catalog": lore_catalog,
        }

    return state_loader
