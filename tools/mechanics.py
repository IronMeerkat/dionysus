"""⚙️ Deterministic CRUD + prompt rendering for campaign mechanics documents.

Mechanics documents are negotiated with the organizer by the
campaign-negotiation agent and persisted as ``CampaignMechanic`` rows -- one
self-contained markdown system per row ("The Leash", "The Season Clock").
No LLM ever writes these rows directly; the agent goes through the
LangChain tools in ``tools/campaign_negotiation.py``. This module is kept
free of imports from other tool modules so both ``tools/campaign_admin.py``
(overview rendering) and the negotiation factory can use it without cycles.
"""
from logging import getLogger

from sqlalchemy.orm import Session

from database.models import CampaignMechanic
from database.postgres_connection import db_session

logger = getLogger(__name__)


# ------------------------------------------------------------------
# Lookups + CRUD
# ------------------------------------------------------------------

def list_mechanics(campaign_id: int) -> list[CampaignMechanic]:
    """⚙️ All mechanics documents for a campaign (detached), ordered by title."""
    with db_session() as s:
        return (
            s.query(CampaignMechanic)
            .filter(CampaignMechanic.campaign_id == campaign_id)
            .order_by(CampaignMechanic.title)
            .all()
        )


def _find_mechanic(s: Session, campaign_id: int, title: str) -> CampaignMechanic | None:
    clean = title.strip().lower()
    return next(
        (m for m in s.query(CampaignMechanic).filter(CampaignMechanic.campaign_id == campaign_id)
         if m.title.lower() == clean),
        None,
    )


def get_mechanic(campaign_id: int, title: str) -> CampaignMechanic | None:
    """⚙️ Fetch one mechanics document (detached) by (campaign, title), case-insensitive."""
    with db_session() as s:
        return _find_mechanic(s, campaign_id, title)


def upsert_mechanic(campaign_id: int, title: str, content: str) -> CampaignMechanic:
    """⚙️ Create or replace one mechanics document by (campaign, title).

    Matching is case-insensitive so the agent doesn't fork a system by
    re-casing its title. Content is replaced wholesale -- these documents
    supersede themselves ("supersedes all prior leash text").
    """
    with db_session() as s:
        existing = _find_mechanic(s, campaign_id, title)
        if existing is None:
            existing = CampaignMechanic(
                campaign_id=campaign_id, title=title.strip(), content=content.strip()
            )
            s.add(existing)
            logger.info(f"⚙️ Creating mechanics doc '{title.strip()}' for campaign {campaign_id}")
        else:
            logger.info(f"⚙️ Replacing mechanics doc '{existing.title}' for campaign {campaign_id}")
            existing.content = content.strip()
        s.flush()  # populate defaults before detach
    return existing


def delete_mechanic(campaign_id: int, title: str) -> bool:
    """🗑️ Remove one mechanics document by (campaign, title)."""
    with db_session() as s:
        existing = _find_mechanic(s, campaign_id, title)
        if existing is None:
            logger.warning(f"⚠️ Mechanics doc '{title}' not found in campaign {campaign_id}")
            return False
        title_deleted = existing.title
        s.delete(existing)
    logger.info(f"🗑️ Deleted mechanics doc '{title_deleted}' from campaign {campaign_id}")
    return True


# ------------------------------------------------------------------
# Rendering
# ------------------------------------------------------------------

def render_mechanics(mechanics: list[CampaignMechanic]) -> str:
    """📋 Compact overview block: one line per document (title + first line).

    The full markdown stays behind the read_mechanic tool -- mechanics docs
    are long, and the campaign overview is injected every turn.
    """
    if not mechanics:
        return "(none negotiated yet)"
    lines = []
    for m in mechanics:
        preview = next((ln.strip() for ln in m.content.splitlines() if ln.strip()), "")
        lines.append(f"- {m.title} — {preview[:100]}")
    return "\n".join(lines)


def render_mechanics_full(mechanics: list[CampaignMechanic]) -> str:
    """📜 Every mechanics document in full markdown, for the DM planner prompt.

    Returns an empty string when the campaign has none, so callers can skip
    the block unconditionally.
    """
    return "\n\n---\n\n".join(f"# {m.title}\n\n{m.content}" for m in mechanics)
