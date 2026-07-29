"""🤝 LangChain tool factory for the campaign-negotiation agent.

A deliberately smaller set than the campaign admin's: the negotiation chat
shapes a campaign BEFORE play (premise, contract, starting situation, custom
mechanics documents), so there is no participant state, no NPC roster, and
no memory management here. Each tool closes over ``campaign_id`` so the
model never has to pass (or guess) it, and every success message starts
with ✅ so the socket layer can notify the UI.
"""
from logging import getLogger

from langchain.tools import tool

from tools.campaign_admin import (
    edit_contract,
    edit_story_background,
    render_campaign_overview,
)
from tools.mechanics import (
    delete_mechanic as _delete_mechanic,
    get_mechanic as _get_mechanic,
    list_mechanics as _list_mechanics,
    render_mechanics,
    upsert_mechanic as _upsert_mechanic,
)
from tools.world_state import (
    set_location as _set_location,
    set_world_clock as _set_world_clock,
)

logger = getLogger(__name__)


def build_campaign_negotiation_tools(campaign_id: int) -> list:
    """Build the LangChain tool set for the campaign_negotiation agent, bound
    to one campaign.

    Async wrappers around the sync DB helpers so they run on the event-loop
    thread, matching how the rest of the app uses the shared SQLAlchemy
    session.
    """

    @tool
    async def get_campaign_overview() -> str:
        """Read the campaign's full current configuration: name, lore world,
        current scene location, narrative clock, story background, the story
        contract, negotiated mechanics documents, open quest threads and
        active faction clocks. The overview is also refreshed in your system
        context every turn; call this for the freshest read right after a
        change.
        """
        return render_campaign_overview(campaign_id)

    @tool
    async def update_story_background(story_background: str) -> str:
        """Replace the campaign's static story premise / background (free-form
        text). This is the negotiated elevator-pitch setup, not scene
        narration.
        """
        return edit_story_background(campaign_id, story_background)

    @tool
    async def update_contract(updates: dict[str, str]) -> str:
        """Merge one or more fields into the campaign's story contract. Only
        known fields are accepted: tone, rules_strictness, lethality, humor,
        gore, romance, nsfw, railroading, player_agency. Unknown fields are
        ignored and reported back.
        """
        return edit_contract(campaign_id, updates)

    @tool
    async def update_location(location: str) -> str:
        """Set the campaign's starting scene location (free-form, e.g.
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
    async def list_mechanics() -> str:
        """List the campaign's negotiated mechanics documents (title plus a
        one-line preview each). Use read_mechanic with a title to fetch a
        document's full markdown before revising it.
        """
        return render_mechanics(_list_mechanics(campaign_id))

    @tool
    async def read_mechanic(title: str) -> str:
        """Read the full markdown of one negotiated mechanics document by its
        title (case-insensitive). Always read the existing document before
        replacing it with save_mechanic.
        """
        mechanic = _get_mechanic(campaign_id, title)
        if mechanic is None:
            return f"❌ No mechanics document titled '{title.strip()}' in campaign {campaign_id}."
        return f"# {mechanic.title}\n\n{mechanic.content}"

    @tool
    async def save_mechanic(title: str, content: str) -> str:
        """Save a negotiated mechanics document (full markdown). Upserts by
        title: an existing document with the same title is REPLACED, so pass
        the complete new text, not a diff. Only call this after the user has
        explicitly approved the document.
        """
        if not title.strip():
            return "❌ title is empty, nothing saved."
        if not content.strip():
            return "❌ content is empty, nothing saved."
        mechanic = _upsert_mechanic(campaign_id, title, content)
        logger.info(
            f"⚙️ [campaign_negotiation] Saved mechanics doc '{mechanic.title}' "
            f"for campaign {campaign_id} ({len(mechanic.content)} chars)"
        )
        return f"✅ Mechanics document '{mechanic.title}' saved ({len(mechanic.content)} chars)."

    @tool
    async def delete_mechanic(title: str) -> str:
        """Permanently delete one negotiated mechanics document by title.
        Only call this when the user explicitly asks to remove the system.
        """
        if _delete_mechanic(campaign_id, title):
            return f"✅ Mechanics document '{title.strip()}' deleted from campaign {campaign_id}."
        return f"❌ No mechanics document titled '{title.strip()}' in campaign {campaign_id}."

    return [
        get_campaign_overview,
        update_story_background,
        update_contract,
        update_location,
        update_world_clock,
        list_mechanics,
        read_mechanic,
        save_mechanic,
        delete_mechanic,
    ]
