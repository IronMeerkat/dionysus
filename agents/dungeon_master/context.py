"""Shared turn context and the context-loading nodes for the DM supervisor."""
import asyncio
from dataclasses import dataclass
from logging import getLogger

import socketio
from langchain_core.messages import AnyMessage, HumanMessage

from agents.dungeon_master.schemas import DungeonMasterState
from database.graphiti_utils import (
    load_information,
    make_events_group_id,
    make_group_id,
    make_player_prefs_group_id,
    make_secrets_group_id,
)
from database.models.conversation import Conversation
from tools.participants import render_npc_states, render_player_state
from tools.world_state import (
    list_faction_clocks,
    list_open_threads,
    render_clocks,
    render_threads,
)
from hephaestus.settings import settings

info_limits = settings.graphiti.information_limits
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
    def npc_names(self) -> str:
        names = [c.name for c in self.conversation.characters]
        return ", ".join(names) if names else "(none)"

    @property
    def npc_descriptions(self) -> str:
        return "\n\n".join(f"**{c.name}**:\n{c.description}" for c in self.conversation.characters)

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
        clocks, and participant mechanical state.

        Cheap, so it runs first -- the intent router only needs player_state,
        which lets the slow Graphiti retrieval overlap with intent classification.
        """
        threads_rows, clocks_rows, player_state, npc_states = await asyncio.gather(
            asyncio.to_thread(list_open_threads, ctx.campaign.id),
            asyncio.to_thread(list_faction_clocks, ctx.campaign.id),
            asyncio.to_thread(render_player_state, ctx.campaign.id, ctx.player.id),
            asyncio.to_thread(render_npc_states, ctx.campaign.id, list(ctx.conversation.characters)),
        )
        threads = render_threads(threads_rows)
        clocks = render_clocks(clocks_rows)

        logger.info(
            f"🗄️ World state loaded: {len(threads.splitlines())} threads, "
            f"{len(clocks.splitlines())} clocks, "
            f"{len(player_state.splitlines())} player-state, "
            f"{len(npc_states.splitlines())} npc-state lines"
        )
        return {
            "messages": [],
            "open_threads": threads,
            "faction_clocks": clocks,
            "player_state": player_state,
            "active_npc_states": npc_states,
        }

    return state_loader


def make_graphiti_loader(ctx: DMContext):
    async def graphiti_loader(state: DungeonMasterState) -> dict:
        """📚 Load lore, world events, DM secrets, and player prefs from
        Graphiti in parallel. Runs concurrently with the intent router."""
        query = ctx.last_human_query(state)

        group_ids = [
            make_group_id("lore", ctx.campaign.lore_world),
            make_events_group_id(ctx.campaign.id),
            make_secrets_group_id(ctx.campaign.id),
            make_player_prefs_group_id(ctx.campaign.id),
        ]
        lore, events, secrets, prefs = await asyncio.gather(
            *(load_information(query=query, group_ids=[gid], limit=info_limits.lore)
              for gid in group_ids)
        )

        logger.info(
            f"📚 Graphiti context loaded: {len(lore.splitlines())} lore, "
            f"{len(events.splitlines())} events, {len(secrets.splitlines())} secrets, "
            f"{len(prefs.splitlines())} prefs lines"
        )
        return {
            "messages": [],
            "lore": lore,
            "world_events": events,
            "secret_knowledge": secrets,
            "player_prefs": prefs or "(nothing learned yet)",
        }

    return graphiti_loader
