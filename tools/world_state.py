"""Deterministic world-state helpers: quest threads, faction clocks, world clock.

These are Layer-1 deterministic functions ("narrator decorates, canon decides"):
LLM nodes produce structured updates, and these helpers apply them to Postgres
with validation and audit logging. No LLM ever writes state directly.
"""
from logging import getLogger

from database.models import FactionClock, QuestThread, WorldState
from database.postgres_connection import session

logger = getLogger(__name__)

THREAD_ACTIONS = ("open", "progress", "resolve", "abandon")


# ------------------------------------------------------------------
# Quest threads
# ------------------------------------------------------------------

def list_open_threads(campaign_id: int) -> list[QuestThread]:
    """🧵 All open quest threads for a campaign, oldest first."""
    return (
        session.query(QuestThread)
        .filter(QuestThread.campaign_id == campaign_id, QuestThread.status == "open")
        .order_by(QuestThread.created_at)
        .all()
    )


def _find_thread(campaign_id: int, title: str) -> QuestThread | None:
    return (
        session.query(QuestThread)
        .filter(
            QuestThread.campaign_id == campaign_id,
            QuestThread.title.ilike(title.strip()),
        )
        .first()
    )


def apply_thread_update(campaign_id: int, title: str, action: str, note: str = "") -> QuestThread | None:
    """🧵 Apply a single structured thread update.

    Actions: ``open`` (creates if missing), ``progress`` (append note),
    ``resolve`` / ``abandon`` (close the loop).
    """
    if action not in THREAD_ACTIONS:
        logger.error(f"❌ Unknown thread action '{action}' for '{title}', skipping")
        return None

    thread = _find_thread(campaign_id, title)

    if action == "open":
        if thread is not None:
            if thread.status != "open":
                thread.status = "open"
                logger.info(f"🧵 Re-opened thread '{title}' (campaign {campaign_id})")
            if note:
                thread.notes = f"{thread.notes}\n{note}".strip()
        else:
            thread = QuestThread(campaign_id=campaign_id, title=title.strip(), notes=note)
            session.add(thread)
            logger.info(f"🧵 Opened thread '{title}' (campaign {campaign_id})")
    elif thread is None:
        logger.warning(f"⚠️ Thread '{title}' not found for action '{action}', opening it instead")
        thread = QuestThread(campaign_id=campaign_id, title=title.strip(), notes=note)
        if action in ("resolve", "abandon"):
            thread.status = "resolved" if action == "resolve" else "abandoned"
        session.add(thread)
    elif action == "progress":
        if note:
            thread.notes = f"{thread.notes}\n{note}".strip()
        logger.info(f"🧵 Progressed thread '{title}': {note[:80]}")
    else:  # resolve | abandon
        thread.status = "resolved" if action == "resolve" else "abandoned"
        if note:
            thread.notes = f"{thread.notes}\n{note}".strip()
        logger.info(f"🧵 Thread '{title}' marked {thread.status}")

    session.commit()
    return thread


def render_threads(threads: list[QuestThread]) -> str:
    """Render open threads as a prompt-ready block."""
    if not threads:
        return "(no open quest threads)"
    lines = []
    for t in threads:
        note = f" -- {t.notes.strip().splitlines()[-1]}" if t.notes.strip() else ""
        lines.append(f"- {t.title}{note}")
    return "\n".join(lines)


# ------------------------------------------------------------------
# Faction clocks
# ------------------------------------------------------------------

def list_faction_clocks(campaign_id: int, include_finished: bool = False) -> list[FactionClock]:
    """⏰ Faction clocks for a campaign (active only by default)."""
    query = session.query(FactionClock).filter(FactionClock.campaign_id == campaign_id)
    if not include_finished:
        query = query.filter(FactionClock.status == "active")
    return query.order_by(FactionClock.created_at).all()


def _find_clock(campaign_id: int, faction_name: str) -> FactionClock | None:
    return (
        session.query(FactionClock)
        .filter(
            FactionClock.campaign_id == campaign_id,
            FactionClock.faction_name.ilike(faction_name.strip()),
            FactionClock.status == "active",
        )
        .first()
    )


def create_faction_clock(
    campaign_id: int,
    faction_name: str,
    goal: str,
    ticks_max: int = 6,
    next_move: str = "",
) -> FactionClock:
    """⏰ Start a new progress clock for a faction agenda."""
    existing = _find_clock(campaign_id, faction_name)
    if existing is not None and existing.goal.strip().lower() == goal.strip().lower():
        logger.info(f"⏰ Clock for '{faction_name}' / '{goal[:60]}' already exists, reusing")
        return existing

    clock = FactionClock(
        campaign_id=campaign_id,
        faction_name=faction_name.strip(),
        goal=goal.strip(),
        ticks_max=max(2, ticks_max),
        next_move=next_move,
    )
    session.add(clock)
    session.commit()
    logger.info(f"⏰ New faction clock: '{faction_name}' -> '{goal[:80]}' (0/{clock.ticks_max})")
    return clock


def advance_faction_clock(
    campaign_id: int,
    faction_name: str,
    ticks: int,
    reason: str = "",
    next_move: str | None = None,
) -> FactionClock | None:
    """⏰ Tick a faction clock forward (clamped); mark completed when it fills."""
    clock = _find_clock(campaign_id, faction_name)
    if clock is None:
        logger.warning(f"⚠️ No active clock for faction '{faction_name}' (campaign {campaign_id})")
        return None

    ticks = max(0, ticks)
    clock.ticks_current = min(clock.ticks_max, clock.ticks_current + ticks)
    if next_move is not None:
        clock.next_move = next_move
    if clock.filled:
        clock.status = "completed"
        logger.warning(f"🔔 Faction clock FILLED: '{clock.faction_name}' achieves '{clock.goal[:80]}'")
    else:
        logger.info(
            f"⏰ '{clock.faction_name}' +{ticks} -> {clock.ticks_current}/{clock.ticks_max}"
            + (f" ({reason[:80]})" if reason else "")
        )
    session.commit()
    return clock


def render_clocks(clocks: list[FactionClock]) -> str:
    """Render faction clocks as a prompt-ready block."""
    if not clocks:
        return "(no active faction clocks)"
    lines = []
    for c in clocks:
        move = f" | next move: {c.next_move.strip()}" if c.next_move.strip() else ""
        lines.append(f"- {c.faction_name} [{c.ticks_current}/{c.ticks_max}]: {c.goal}{move}")
    return "\n".join(lines)


# ------------------------------------------------------------------
# World state (current scene + narrative clock)
# ------------------------------------------------------------------

def get_world_state(campaign_id: int) -> WorldState | None:
    """🌍 Fetch the campaign's world state row, or None if it does not exist."""
    return session.query(WorldState).filter(WorldState.campaign_id == campaign_id).first()


def ensure_world_state(campaign_id: int) -> WorldState:
    """🌍 Get the campaign's world state row, creating an empty one if missing."""
    world_state = get_world_state(campaign_id)
    if world_state is None:
        world_state = WorldState(campaign_id=campaign_id)
        session.add(world_state)
        session.commit()
        logger.info(f"🌍 Created world_state row for campaign {campaign_id}")
    return world_state


def set_location(campaign_id: int, location: str) -> None:
    """📍 Update the campaign's current scene location."""
    if not location or not location.strip():
        return
    world_state = ensure_world_state(campaign_id)
    world_state.location = location.strip()
    session.add(world_state)
    session.commit()
    logger.info(f"📍 Location set to '{world_state.location}' (campaign {campaign_id})")


# ------------------------------------------------------------------
# World clock
# ------------------------------------------------------------------

def set_world_clock(campaign_id: int, new_value: str) -> None:
    """🕰️ Advance the narrative clock for a campaign."""
    if not new_value or not new_value.strip():
        return
    world_state = ensure_world_state(campaign_id)
    world_state.world_clock = new_value.strip()
    session.add(world_state)
    session.commit()
    logger.info(f"🕰️ World clock set to '{world_state.world_clock}' (campaign {campaign_id})")
