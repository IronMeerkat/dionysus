"""Shared turn context and the context-loading nodes for the DM supervisor."""
import asyncio
from dataclasses import dataclass, field
from logging import getLogger

import socketio
from langchain_core.messages import AnyMessage, HumanMessage

from agents.dungeon_master.schemas import DungeonMasterState
from database.models import Campaign, DMSecret, PlayerPreference, WorldEvent
from database.models.conversation import Conversation
from tools.mechanics import list_mechanics, render_mechanics_full
from tools.participants import render_participant_state, render_participant_states
from tools.status_effects import character_sheet_by_id
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

    # Immutable scalar snapshots captured at construction, so threaded
    # helpers can take plain ints instead of touching ORM objects.
    campaign_id: int = field(init=False)
    player_id: int | None = field(init=False)

    def __post_init__(self) -> None:
        self.campaign_id = self.conversation.campaign_id
        self.player_id = self.conversation.player_id

    # ------------------------------------------------------------------
    # Data freshness model
    # ------------------------------------------------------------------
    # ``ctx.conversation`` is a DETACHED snapshot loaded when the socket
    # session started: it owns identity, the roster, and the message
    # buffer/bookkeeping, and its eagerly-loaded relationships (campaign,
    # player, characters, messages) stay readable forever. Anything that
    # CHANGES during play -- scene location, narrative clock, story
    # background, character sheets -- is fetched fresh per property access
    # through its own task session, which is safe from any thread (event
    # loop or ``asyncio.to_thread`` worker).

    @property
    def campaign(self) -> Campaign:
        """The snapshot Campaign row (id, name, contract, lore world)."""
        return self.conversation.campaign

    def _fresh_campaign(self) -> Campaign | None:
        return Campaign.get(id=self.campaign_id)

    @property
    def player(self):
        return self.conversation.player

    @property
    def world_clock(self) -> str:
        campaign = self._fresh_campaign()
        return (campaign.world_clock if campaign else "") or "(unspecified)"

    @property
    def location(self) -> str:
        campaign = self._fresh_campaign()
        return campaign.location if campaign else ""

    @property
    def story_background(self) -> str:
        campaign = self._fresh_campaign()
        return (campaign.story_background if campaign else "") or ""

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
        return "\n\n".join(
            f"**{c.name}**:\n{character_sheet_by_id(c.id)}" for c in self.conversation.characters
        )

    @property
    def player_sheet(self) -> str:
        """The PC's character card with permanent status effects appended."""
        return character_sheet_by_id(self.player_id)

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

        Cheap, so it runs first -- lore itself is no longer catalogued here;
        the intent router retrieves it by vector recall downstream.
        """
        def _participant_states() -> tuple[str, str]:
            npcs = [c for c in ctx.conversation.characters if c.id != ctx.player_id]
            return (
                render_participant_state(ctx.campaign_id, ctx.player_id),
                render_participant_states(ctx.campaign_id, npcs),
            )

        (threads_rows, clocks_rows, (player_state, npc_states),
         events, secrets, prefs) = await asyncio.gather(
            asyncio.to_thread(list_open_threads, ctx.campaign_id),
            asyncio.to_thread(list_faction_clocks, ctx.campaign_id),
            asyncio.to_thread(_participant_states),
            asyncio.to_thread(WorldEvent.recent, ctx.campaign_id),
            asyncio.to_thread(DMSecret.recent, ctx.campaign_id),
            asyncio.to_thread(PlayerPreference.recent, ctx.campaign_id),
        )
        threads = render_threads(threads_rows)
        clocks = render_clocks(clocks_rows)

        logger.info(
            f"🗄️ World state loaded: {len(threads.splitlines())} threads, "
            f"{len(clocks.splitlines())} clocks, "
            f"{len(events.splitlines())} events, {len(secrets.splitlines())} secrets, "
            f"{len(prefs.splitlines())} prefs, "
            f"{len(player_state.splitlines())} player-state, "
            f"{len(npc_states.splitlines())} npc-state lines"
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
        }

    return state_loader
