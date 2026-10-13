"""State loader node: embeds query, detects OOC, and loads lore + world state from Postgres."""
import asyncio
import re
from logging import getLogger

from langgraph.graph.state import CompiledStateGraph

from agents.dungeon_master.schemas import DMContext
from database.models import Campaign, DMSecret, PlayerPreference, World, WorldEvent
from database.models.lore import LoreEntry
from database.models.routing import LABEL_OOC, RoutingExemplar
from database.session_utils import embedder
from hephaestus.agent_architectures import AgentSwarmState, function_to_graph
from hephaestus.settings import settings
from tools.participants import render_participant_state, render_participant_states
from tools.status_effects import character_sheet_by_id
from tools.world_state import list_faction_clocks, list_open_threads, render_clocks, render_threads

logger = getLogger(__name__)

LORE_TOP_K = settings.memory.recall.lore_top_k
_OOC_MARKERS = re.compile(r"^\s*(?:\(\s*)?ooc[\s:)\]]|^\s*\(\(", re.IGNORECASE)
_WRAPPED_IN_PARENS = re.compile(r"^\s*\(+.*?\)+\s*$", re.DOTALL)


def spawn_state_loader(ctx: DMContext) -> CompiledStateGraph:
    conversation = ctx.conversation

    async def state_loader(state: AgentSwarmState) -> dict:
        ctx.plan = None
        ctx.adjudication = None
        ctx.outcome_narrated = False
        query = ctx.last_human_query(state.messages, fallback="").strip()
        ctx.query_vector = None
        if query:
            try:
                ctx.query_vector = await embedder.aembed_query(query)
            except Exception:
                logger.exception("💥 [state_loader] query embedding failed; degrading to recency")

        ctx.ooc = bool(query and (_OOC_MARKERS.match(query) or _WRAPPED_IN_PARENS.match(query)))
        if not ctx.ooc and ctx.query_vector is not None:
            cfg = settings.memory.routing
            try:
                neighbors = await asyncio.to_thread(RoutingExemplar.nearest, ctx.query_vector, cfg.exemplars_top_k)
                if neighbors:
                    ooc_votes = sum(1 for ex, _ in neighbors if ex.label == LABEL_OOC)
                    story_votes = len(neighbors) - ooc_votes
                    margin = abs(ooc_votes - story_votes) / len(neighbors)
                    if ooc_votes > story_votes and neighbors[0][1] <= cfg.tau_confident and margin >= cfg.tau_margin:
                        ctx.ooc = True
            except Exception:
                logger.exception("💥 Exemplar routing search failed; treating as story")

        world = await asyncio.to_thread(World.get_world_by_name, conversation.campaign.lore_world)
        if world is None:
            ctx.lore = "(world has no entries yet)"
        elif ctx.query_vector is None:
            ctx.lore = "(no lore retrieved this turn)"
        else:
            try:
                entries = await asyncio.to_thread(LoreEntry.search, world, ctx.query_vector, LORE_TOP_K)
                ctx.lore = (
                    "\n\n---\n\n".join(f"# {e.title}\n\n{e.content}" for e in entries)
                    if entries else "(no lore retrieved this turn)"
                )
            except Exception:
                logger.exception("💥 [state_loader] lore vector search failed")
                ctx.lore = "(lore retrieval failed this turn)"

        npcs = [c for c in conversation.characters if c.id != ctx.player_id]
        events_coro = (
            asyncio.to_thread(WorldEvent.relevant_and_recent, ctx.campaign_id, ctx.query_vector)
            if ctx.query_vector is not None else asyncio.to_thread(WorldEvent.recent, ctx.campaign_id)
        )
        secrets_coro = (
            asyncio.to_thread(DMSecret.relevant_and_recent, ctx.campaign_id, ctx.query_vector)
            if ctx.query_vector is not None else asyncio.to_thread(DMSecret.recent, ctx.campaign_id)
        )
        campaign_row, p_sheet, threads_rows, clocks_rows, p_state, n_states, events, secrets, prefs = await asyncio.gather(
            asyncio.to_thread(Campaign.get, ctx.campaign_id),
            asyncio.to_thread(character_sheet_by_id, ctx.player_id),
            asyncio.to_thread(list_open_threads, ctx.campaign_id),
            asyncio.to_thread(list_faction_clocks, ctx.campaign_id),
            asyncio.to_thread(render_participant_state, ctx.campaign_id, ctx.player_id),
            asyncio.to_thread(render_participant_states, ctx.campaign_id, npcs),
            events_coro,
            secrets_coro,
            asyncio.to_thread(PlayerPreference.recent, ctx.campaign_id),
        )
        ctx.location = (campaign_row.location if campaign_row else "") or ""
        ctx.world_clock = (campaign_row.world_clock if campaign_row else "") or "(unspecified)"
        ctx.story_background = (campaign_row.story_background if campaign_row else "") or ""
        ctx.player_sheet = p_sheet
        ctx.open_threads = render_threads(threads_rows)
        ctx.faction_clocks = render_clocks(clocks_rows)
        ctx.player_state = p_state
        ctx.active_npc_states = n_states
        ctx.world_events = events
        ctx.secret_knowledge = secrets
        ctx.player_prefs = prefs or "(nothing learned yet)"
        logger.info(f"🗄️ World state loaded (ooc={ctx.ooc})")
        return {"messages": []}

    return function_to_graph(state_loader, name="state_loader")
