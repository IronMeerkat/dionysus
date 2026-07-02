"""Deterministic campaign-admin helpers + LangChain tool factory.

Layer-1 deterministic functions ("narrator decorates, canon decides") for the
out-of-character campaign configuration the organizer manages: story
background, the story contract, current scene location, narrative clock, quest
threads and faction clocks. The DM canon manager mutates world state during
play; these tools let a human (via the ``campaign_admin`` agent) read and edit
the same knobs between sessions, with validation and audit logging. No LLM
ever writes state directly -- the agent calls these tools.
"""
from logging import getLogger

from langchain.tools import tool

from database.models import Campaign, QuestThread
from database.postgres_connection import session
from tools.world_state import (
    THREAD_ACTIONS,
    advance_faction_clock as _advance_faction_clock,
    apply_thread_update as _apply_thread_update,
    create_faction_clock as _create_faction_clock,
    list_faction_clocks as _list_faction_clocks,
    render_clocks,
    render_threads,
    set_location as _set_location,
    set_world_clock as _set_world_clock,
)

logger = getLogger(__name__)

# The well-known story-contract dials (see settings.yaml default_contract).
CONTRACT_KEYS = (
    "tone",
    "rules_strictness",
    "lethality",
    "humor",
    "gore",
    "romance",
    "nsfw",
    "railroading",
    "player_agency",
)


# ------------------------------------------------------------------
# Deterministic helpers
# ------------------------------------------------------------------

def get_campaign_row(campaign_id: int) -> Campaign | None:
    """🏰 Fetch the Campaign row, or None."""
    return session.query(Campaign).filter(Campaign.id == campaign_id).first()


def list_threads(campaign_id: int, include_closed: bool = False) -> list[QuestThread]:
    """🧵 Quest threads for a campaign (open only by default), oldest first."""
    query = session.query(QuestThread).filter(QuestThread.campaign_id == campaign_id)
    if not include_closed:
        query = query.filter(QuestThread.status == "open")
    return query.order_by(QuestThread.created_at).all()


def render_campaign_overview(campaign_id: int) -> str:
    """📋 Render the campaign's full current configuration as a prompt block.

    Pulled fresh on every agent turn so the system prompt always reflects the
    latest DB state (including changes made by tool calls in prior turns).
    """
    campaign = get_campaign_row(campaign_id)
    if campaign is None:
        return f"❌ Campaign {campaign_id} not found."

    contract = campaign.contract or {}
    contract_lines = "\n".join(
        f"  - {key}: {contract.get(key, '(unset)')}" for key in CONTRACT_KEYS
    ) or "  (none)"

    threads_block = render_threads(list_threads(campaign_id, include_closed=False))
    clocks_block = render_clocks(_list_faction_clocks(campaign_id, include_finished=False))

    return (
        f"Campaign #{campaign.id}: {campaign.name}\n"
        f"lore_world: {campaign.lore_world}\n"
        f"location: {campaign.location or '(unset)'}\n"
        f"world_clock: {campaign.world_clock or '(unset)'}\n\n"
        f"story_background:\n{campaign.story_background or '(empty)'}\n\n"
        f"contract:\n{contract_lines}\n\n"
        f"open quest threads:\n{threads_block}\n\n"
        f"active faction clocks:\n{clocks_block}"
    )


# ------------------------------------------------------------------
# LangChain tool factory (bound to a single campaign)
# ------------------------------------------------------------------

def build_campaign_admin_tools(campaign_id: int) -> list:
    """Build the LangChain tool set for the campaign_admin agent, bound to one campaign.

    Each tool closes over ``campaign_id`` so the model never has to pass (or
    guess) it. Tools are async wrappers around the sync DB helpers so they run
    on the event-loop thread, matching how the rest of the app uses the
    shared SQLAlchemy session.
    """

    @tool
    async def get_campaign_overview() -> str:
        """Read the campaign's full current configuration: name, lore world,
        current scene location, narrative clock, story background, the story
        contract, open quest threads and active faction clocks. Call this
        whenever the user asks "what's the current state" or after a change.
        """
        return render_campaign_overview(campaign_id)

    @tool
    async def update_story_background(story_background: str) -> str:
        """Replace the campaign's static story premise / background (free-form
        text). This is the elevator-pitch setup chosen at creation, not scene
        narration.
        """
        background = story_background.strip()
        if not background:
            return "❌ story_background is empty, nothing updated."
        campaign = get_campaign_row(campaign_id)
        if campaign is None:
            return f"❌ Campaign {campaign_id} not found."
        campaign.story_background = background
        session.add(campaign)
        session.commit()
        logger.info(f"📜 [campaign_admin] Updated story_background for campaign {campaign_id}")
        return f"✅ Story background updated ({len(background)} chars)."

    @tool
    async def update_contract(updates: dict[str, str]) -> str:
        """Merge one or more fields into the campaign's story contract. Only
        known fields are accepted: tone, rules_strictness, lethality, humor,
        gore, romance, nsfw, railroading, player_agency. Unknown fields are
        ignored and reported back.
        """
        campaign = get_campaign_row(campaign_id)
        if campaign is None:
            return f"❌ Campaign {campaign_id} not found."
        contract = dict(campaign.contract or {})
        applied: list[str] = []
        ignored: list[str] = []
        for key, value in (updates or {}).items():
            if key in CONTRACT_KEYS:
                contract[key] = str(value)
                applied.append(key)
            else:
                ignored.append(key)
        if not applied:
            return f"❌ No valid contract fields. Known: {', '.join(CONTRACT_KEYS)}."
        campaign.contract = contract
        session.add(campaign)
        session.commit()
        logger.info(f"📜 [campaign_admin] Updated contract fields {applied} for campaign {campaign_id}")
        parts = ", ".join(f"{key}={contract[key]}" for key in applied)
        msg = f"✅ Contract updated: {parts}."
        if ignored:
            msg += f" Ignored unknown fields: {', '.join(ignored)}."
        return msg

    @tool
    async def update_location(location: str) -> str:
        """Set the campaign's current scene location (free-form, e.g.
        'The Rusty Anchor tavern').
        """
        if not location or not location.strip():
            return "❌ location is empty, nothing updated."
        _set_location(campaign_id, location)
        return f"✅ Location set to '{location.strip()}'."

    @tool
    async def update_world_clock(world_clock: str) -> str:
        """Set the campaign's narrative clock (free-form in-fiction time, e.g.
        'Dusk, day 3 of the Festival of Lanterns').
        """
        if not world_clock or not world_clock.strip():
            return "❌ world_clock is empty, nothing updated."
        _set_world_clock(campaign_id, world_clock)
        return f"✅ World clock set to '{world_clock.strip()}'."

    @tool
    async def list_quest_threads(include_closed: bool = False) -> str:
        """List the campaign's quest threads (open narrative loops). Set
        include_closed=true to also see resolved/abandoned threads.
        """
        threads = list_threads(campaign_id, include_closed=include_closed)
        if not threads:
            scope = "open" if not include_closed else "all"
            return f"(no {scope} quest threads)"
        lines = []
        for t in threads:
            note = f" — {t.notes.strip().splitlines()[-1]}" if t.notes.strip() else ""
            lines.append(f"- [{t.status}] {t.title}{note}")
        return "\n".join(lines)

    @tool
    async def manage_quest_thread(title: str, action: str, note: str = "") -> str:
        """Create or update a quest thread. ``action`` must be one of:
        open (create or reopen), progress (append a note), resolve (close as
        resolved), abandon (close as abandoned).
        """
        if action not in THREAD_ACTIONS:
            return f"❌ action must be one of {list(THREAD_ACTIONS)}, got '{action}'."
        thread = _apply_thread_update(campaign_id, title, action, note)
        if thread is None:
            return f"❌ Could not apply '{action}' to thread '{title}'."
        return f"✅ Thread '{thread.title}' {action}ed (status={thread.status})."

    @tool
    async def list_faction_clocks(include_finished: bool = False) -> str:
        """List the campaign's faction clocks (offscreen faction agendas). Set
        include_finished=true to also see completed/stalled clocks.
        """
        clocks = _list_faction_clocks(campaign_id, include_finished=include_finished)
        if not clocks:
            scope = "active" if not include_finished else "all"
            return f"(no {scope} faction clocks)"
        return render_clocks(clocks)

    @tool
    async def create_faction_clock(
        faction_name: str, goal: str, ticks_max: int = 6, next_move: str = ""
    ) -> str:
        """Start a new progress clock for a faction's offscreen agenda.
        ``ticks_max`` is the number of segments the clock fills over (min 2,
        default 6); when it fills, the faction's goal comes to pass.
        """
        clock = _create_faction_clock(
            campaign_id, faction_name, goal, ticks_max=ticks_max, next_move=next_move
        )
        return f"✅ Faction clock created: {clock.faction_name} [0/{clock.ticks_max}] -> {clock.goal}."

    @tool
    async def advance_faction_clock(
        faction_name: str, ticks: int, reason: str = "", next_move: str = ""
    ) -> str:
        """Tick a faction's clock forward by ``ticks`` segments (clamped to the
        clock size). When it fills, the faction's goal comes to pass. Pass
        ``next_move`` to update the faction's planned next action.
        """
        resolved_next = next_move if next_move else None
        clock = _advance_faction_clock(
            campaign_id, faction_name, ticks, reason=reason, next_move=resolved_next
        )
        if clock is None:
            return f"❌ No active clock for faction '{faction_name}'."
        status = "FILLED — goal achieved!" if clock.filled else f"{clock.ticks_current}/{clock.ticks_max}"
        return f"✅ {clock.faction_name} clock advanced to {status}."

    return [
        get_campaign_overview,
        update_story_background,
        update_contract,
        update_location,
        update_world_clock,
        list_quest_threads,
        manage_quest_thread,
        list_faction_clocks,
        create_faction_clock,
        advance_faction_clock,
    ]
