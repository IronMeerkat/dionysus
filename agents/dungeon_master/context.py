"""Shared turn context and the context-loading nodes for the DM supervisor."""
import asyncio
from dataclasses import dataclass, field
from logging import getLogger

import socketio
from langchain_core.messages import AnyMessage, HumanMessage

from agents.dungeon_master.schemas import DungeonMasterState
from database.models import Campaign, DMSecret, PlayerPreference, World, WorldEvent
from database.models.conversation import Conversation
from database.models.lore import LoreEntry
from database.session_utils import embedder
from hephaestus.settings import settings
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

# How many lore documents vector recall pulls per turn.
LORE_TOP_K = settings.memory.recall.lore_top_k


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


async def _retrieve_lore(ctx: DMContext, state: DungeonMasterState, vector: list[float] | None) -> str:
    """🔍 Vector lore recall over the world's closest entries -- no title
    catalog, no classifier picking ids. Reuses the turn's query vector
    (embedded once by state_loader); only when that is missing does it
    embed the player's message itself.

    Fail-secure: an embedding or search failure is logged and degrades the
    turn to "(lore retrieval failed this turn)" -- never a fabricated document.
    """
    if vector is None:
        latest = next((m for m in reversed(state.messages) if m.type == "human"), None)
        if latest is None:
            logger.warning("⚠️ [state_loader] no player message to retrieve lore for")
            return "(no lore retrieved this turn)"
        try:
            vector = await embedder.aembed_query(latest.content)
        except Exception:
            logger.exception("💥 [state_loader] lore query embedding failed")
            return "(lore retrieval failed this turn)"

    world_name = ctx.campaign.lore_world
    world = await asyncio.to_thread(World.get_world_by_name, world_name)
    if world is None:
        logger.warning(f"⚠️ [state_loader] world '{world_name}' not found for lore recall")
        return "(world has no entries yet)"

    try:
        entries = await asyncio.to_thread(LoreEntry.search, world, vector, LORE_TOP_K)
    except Exception:
        logger.exception(f"💥 [state_loader] lore vector search failed for world '{world_name}'")
        return "(lore retrieval failed this turn)"

    if not entries:
        return "(no lore retrieved this turn)"
    titles = ", ".join(f"'{e.title}'" for e in entries)
    logger.info(f"🔍 [state_loader] vector recall hit {len(entries)} lore document(s): {titles}")
    return "\n\n---\n\n".join(f"# {e.title}\n\n{e.content}" for e in entries)


def make_state_loader(ctx: DMContext):
    async def state_loader(state: DungeonMasterState) -> dict:
        """🗄️ Load structured world state from Postgres: quest threads, faction
        clocks, participant mechanical state, and the world event / DM secret /
        player preference streams.

        Also embeds the player's latest message exactly once per turn
        (``query_vector``): lore recall, NPC memory recall, exemplar routing,
        and the stream relevance recall all reuse it downstream. Events and
        secrets are recalled by vector relevance unioned with recency when
        the vector is available, recency-only otherwise; preferences stay
        recency-based (they are pacing signals, not topical facts).
        """
        def _participant_states() -> tuple[str, str]:
            npcs = [c for c in ctx.conversation.characters if c.id != ctx.player_id]
            return (
                render_participant_state(ctx.campaign_id, ctx.player_id),
                render_participant_states(ctx.campaign_id, npcs),
            )

        async def _embed_turn_query() -> list[float] | None:
            """🧬 Embed the player's latest message once for the whole turn.

            Fail-secure: an embedder failure is logged and degrades every
            downstream vector recall (lore, memories, streams, routing) to
            its recency-only fallback -- never blocks the turn.
            """
            query = DMContext.last_human_query(state, fallback="")
            if not query.strip():
                logger.warning("⚠️ [state_loader] no player message to embed this turn")
                return None
            try:
                return await embedder.aembed_query(query)
            except Exception:
                logger.exception("💥 [state_loader] turn query embedding failed; vector recalls degrade to recency")
                return None

        # Embed first: the local Ollama call is fast and every vector recall
        # below (streams, lore, NPC memories, routing) reuses it.
        query_vector = await _embed_turn_query()
        lore = await _retrieve_lore(ctx, state, query_vector)

        if query_vector is not None:
            events_coro = asyncio.to_thread(WorldEvent.relevant_and_recent, ctx.campaign_id, query_vector)
            secrets_coro = asyncio.to_thread(DMSecret.relevant_and_recent, ctx.campaign_id, query_vector)
        else:
            events_coro = asyncio.to_thread(WorldEvent.recent, ctx.campaign_id)
            secrets_coro = asyncio.to_thread(DMSecret.recent, ctx.campaign_id)

        (threads_rows, clocks_rows, (player_state, npc_states),
         events, secrets, prefs) = await asyncio.gather(
            asyncio.to_thread(list_open_threads, ctx.campaign_id),
            asyncio.to_thread(list_faction_clocks, ctx.campaign_id),
            asyncio.to_thread(_participant_states),
            events_coro,
            secrets_coro,
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
            "query_vector": query_vector,
            "lore": lore,
            "open_threads": threads,
            "faction_clocks": clocks,
            "player_state": player_state,
            "active_npc_states": npc_states,
            "world_events": events,
            "secret_knowledge": secrets,
            "player_prefs": prefs or "(nothing learned yet)",
        }

    return state_loader
