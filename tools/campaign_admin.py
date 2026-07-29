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

from database import knowledge
from database.models import Campaign, CampaignParticipant, Character, CharacterMemory, QuestThread
from database.postgres_connection import session
from hephaestus.settings import settings
from tools.mechanics import list_mechanics, render_mechanics
from tools.participants import (
    apply_participant_state_update as _apply_participant_state_update,
    ensure_campaign_participant as _ensure_campaign_participant,
    get_campaign_participant as _get_campaign_participant,
    render_participant_state as _render_participant_state,
)
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

# The well-known story-contract dials, in canonical order (settings.yaml default_contract).
CONTRACT_KEYS = tuple(settings.default_contract.model_dump())


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


def edit_story_background(campaign_id: int, story_background: str) -> str:
    """📜 Replace a campaign's static story premise; returns a tool-ready message."""
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


def edit_contract(campaign_id: int, updates: dict[str, str]) -> str:
    """📜 Merge known fields into a campaign's story contract; returns a message."""
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


def render_campaign_overview(campaign_id: int) -> str:
    """📋 Render the campaign's full current configuration as a prompt block.

    Pulled fresh on every agent turn so the system prompt always reflects the
    latest DB state (including changes made by tool calls in prior turns).
    """
    campaign = get_campaign_row(campaign_id)
    if campaign is None:
        return f"❌ Campaign {campaign_id} not found."

    threads_block = render_threads(list_threads(campaign_id, include_closed=False))
    clocks_block = render_clocks(_list_faction_clocks(campaign_id, include_finished=False))
    mechanics_block = render_mechanics(list_mechanics(campaign_id))

    return (
        f"Campaign #{campaign.id}: {campaign.name}\n"
        f"lore_world: {campaign.lore_world}\n"
        f"location: {campaign.location or '(unset)'}\n"
        f"world_clock: {campaign.world_clock or '(unset)'}\n\n"
        f"story_background:\n{campaign.story_background or '(empty)'}\n\n"
        f"{campaign.render_contract()}\n\n"
        f"mechanics documents:\n{mechanics_block}\n\n"
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

    @tool
    async def update_participant_state(
        name: str,
        stats_set: dict[str, int] | None = None,
        status_added: list[dict | str] | None = None,
        status_removed: list[str] | None = None,
        modifiers_set: dict[str, int] | None = None,
        notes: str | None = None,
    ) -> str:
        """Apply a structured patch to a participant's live mechanical state
        (stats, status effects, modifiers, freeform notes).

        ``name`` is the participant's character name (PC or NPC -- they share
        one roster). All other arguments are optional -- pass only the fields
        you want to change:

        - stats_set / modifiers_set: dicts merged by key (overwrite), e.g.
          {"hp": 8, "ac": 14}.
        - status_added: conditions to add. Each entry is either a plain name
          ("poisoned") or an object with mechanics:
          {"name": "poisoned", "note": "venom coursing", "affects": "attack rolls",
           "roll_modifier": -2, "advantage": "disadvantage"}.
          Adding an existing name merges the mechanical keys into it.
        - status_removed: list of condition names to remove, e.g. ["inspired"].
        - notes: freeform text; replaces the existing notes when provided.

        If the named participant is not in this campaign, nothing changes.
        """
        row = _apply_participant_state_update(
            campaign_id,
            name=name,
            stats_set=stats_set,
            status_added=status_added,
            status_removed=status_removed,
            modifiers_set=modifiers_set,
            notes=notes,
        )
        if row is None:
            return f"❌ No character named '{name.strip()}' found in campaign {campaign_id}."

        rendered = _render_participant_state(campaign_id, row.character_id, name.strip())
        return f"✅ Updated '{name.strip()}' state in campaign {campaign_id}:\n{rendered}"

    @tool
    async def list_participant_states() -> str:
        """List every participant in this campaign with their live mechanical
        state: stats, temporary status effects (with roll mechanics),
        modifiers, and notes. Use this to monitor who has what condition
        before changing anything.
        """
        rows = (
            session.query(CampaignParticipant)
            .filter(CampaignParticipant.campaign_id == campaign_id)
            .all()
        )
        if not rows:
            return "🔍 No participants tracked in this campaign yet."
        blocks = []
        for row in rows:
            name = row.character.name if row.character else f"character {row.character_id}"
            blocks.append(_render_participant_state(campaign_id, row.character_id, name))
        logger.info(f"🎲 [campaign_admin] Listed {len(rows)} participant state(s) (campaign {campaign_id})")
        return "\n\n".join(blocks)

    # ------------------------------------------------------------------
    # Character roster (pull from the Character table into this campaign)
    # ------------------------------------------------------------------

    @tool
    async def list_characters(name_substring: str = "") -> str:
        """List character names from the character database, optionally
        filtered by a case-insensitive substring of the name. Use this to
        find the exact name to pass to add_npc_to_campaign. Returns up to 50
        names, alphabetically.
        """
        sub = name_substring.strip()
        query = session.query(Character.name)
        if sub:
            query = query.filter(Character.name.ilike(f"%{sub}%"))
        rows = query.order_by(Character.name).limit(50).all()
        if not rows:
            return f"🔍 No characters found matching '{sub}'." if sub else "🔍 No characters in the database."
        names = [r[0] for r in rows]
        logger.info(f"🎭 [campaign_admin] Listed {len(names)} characters (substring='{sub}', campaign {campaign_id})")
        return "Characters:\n" + "\n".join(f"- {n}" for n in names)

    @tool
    async def add_npc_to_campaign(npc_name: str) -> str:
        """Pull a character from the database by exact name and introduce them
        into this campaign. If the character is not yet part of the campaign
        (no tracked state row), a CampaignParticipant entry is created for them
        so they're on the campaign roster. If they're already in the campaign,
        nothing changes.

        Returns the character's name, current description, and whether they
        were newly added or already present.
        """
        name = npc_name.strip()
        if not name:
            return "❌ npc_name is empty, nothing to add."

        character = session.query(Character).filter(Character.name == name).first()
        if character is None:
            return (
                f"❌ No character named '{name}' found in the database. "
                "Use list_characters to find valid names."
            )

        existing = _get_campaign_participant(campaign_id, character.id)
        if existing is None:
            _ensure_campaign_participant(campaign_id, character.id)
            logger.info(
                f"🎭 [campaign_admin] Introduced NPC '{name}' into campaign "
                f"{campaign_id} (created CampaignParticipant state row)"
            )
            status = f"newly added to campaign {campaign_id}"
        else:
            logger.info(f"🎭 [campaign_admin] NPC '{name}' already in campaign {campaign_id}")
            status = f"already in campaign {campaign_id}"

        description = character.description or "(no description set)"
        return (
            f"✅ NPC '{name}' {status}.\n"
            f"description: {description}"
        )

    # ------------------------------------------------------------------
    # NPC memories (Postgres, via database.knowledge)
    # ------------------------------------------------------------------
    #
    # NPC memories are CharacterMemory rows scoped by (campaign_id,
    # character_id). Every mutation verifies the row's campaign_id before
    # touching it, matching the scoping the other tools enforce.

    def _resolve_character(name: str) -> Character | None:
        return session.query(Character).filter(Character.name == name.strip()).first()

    @tool
    async def list_campaign_npcs() -> str:
        """List the NPCs in this campaign by name. Use this to find the exact
        NPC name before listing or editing that NPC's memories. Includes both
        NPCs tracked in the campaign roster and any NPC that has stored
        memories, even if it has no tracked state row.
        """
        names: set[str] = set()
        rows = (
            session.query(Character.name)
            .join(CampaignParticipant, CampaignParticipant.character_id == Character.id)
            .filter(CampaignParticipant.campaign_id == campaign_id)
            .all()
        )
        names.update(r[0] for r in rows if r[0])

        memory_rows = (
            session.query(Character.name)
            .join(CharacterMemory, CharacterMemory.character_id == Character.id)
            .filter(CharacterMemory.campaign_id == campaign_id)
            .distinct()
            .all()
        )
        names.update(r[0] for r in memory_rows if r[0])

        if not names:
            return f"(no NPCs found in campaign {campaign_id})"
        return "NPCs in this campaign:\n" + "\n".join(f"- {n}" for n in sorted(names))

    @tool
    async def list_npc_memories(npc_name: str) -> str:
        """List all memories stored for an NPC in this campaign. Returns each
        memory's id, title, and creation time. Use the returned id to get,
        update, or delete a specific memory.
        """
        if not npc_name.strip():
            return "❌ npc_name is empty, nothing to list."
        character = _resolve_character(npc_name)
        if character is None:
            return f"❌ No character named '{npc_name.strip()}' found in the database."

        memories = knowledge.list_memories(campaign_id, character.id)
        if not memories:
            return f"🔍 No memories found for NPC '{character.name}' in campaign {campaign_id}."

        logger.info(
            f"🧠 [campaign_admin] Listed {len(memories)} memories "
            f"for NPC '{character.name}' (campaign {campaign_id})"
        )
        return "\n".join(
            f"- id={m['id']} | title='{m['title']}' | created_at={m['created_at']}"
            for m in memories
        )

    @tool
    async def get_npc_memory(memory_id: int) -> str:
        """Fetch the full content of a single NPC memory by id. Use this to
        review a memory before editing or deleting it. The memory must belong
        to an NPC in this campaign.
        """
        memory = knowledge.get_memory(memory_id, campaign_id=campaign_id)
        if memory is None:
            return f"❌ No memory with id={memory_id} in campaign {campaign_id}."
        return f"{memory['title']} (id={memory_id})\n\n{memory['content']}"

    @tool
    async def create_npc_memory(npc_name: str, title: str, content: str) -> str:
        """Add a new memory for an NPC in this campaign. Use this to seed
        backstory, relationships, or other knowledge the NPC should recall.

        The NPC must already exist as a character -- create the NPC (e.g.
        via play) before adding memories. The memory is scoped to this
        campaign and won't leak into others.

        Returns the new memory's id, which you can pass to
        update_npc_memory or delete_npc_memory later.
        """
        name = npc_name.strip()
        clean_title = title.strip()
        body = content.strip()
        if not name:
            return "❌ npc_name is empty, nothing to create."
        if not clean_title:
            return "❌ title is empty, nothing to create."
        if not body:
            return "❌ content is empty, nothing to create."

        character = _resolve_character(name)
        if character is None:
            return (
                f"❌ No character named '{name}' found in the database; "
                "create the NPC before adding memories."
            )

        try:
            memory = await knowledge.save_memory(campaign_id, character.id, clean_title, body)
        except Exception as e:
            logger.exception(f"❌ [campaign_admin] Failed to create memory for NPC '{name}' (campaign {campaign_id})")
            return f"❌ Failed to create memory: {e}"

        logger.info(
            f"🧠 [campaign_admin] Created memory '{clean_title}' for NPC '{name}' "
            f"(id={memory['id']}, campaign {campaign_id})"
        )
        return f"✅ Created memory '{memory['title']}' (id={memory['id']}) for NPC '{name}' in campaign {campaign_id}."

    @tool
    async def update_npc_memory(
        memory_id: int, title: str | None = None, content: str | None = None
    ) -> str:
        """Modify an existing NPC memory's title and/or content. Provide only
        the field(s) you want to change; the other is preserved. The memory
        keeps its id and must belong to an NPC in this campaign.
        """
        try:
            if title is None and content is None:
                return "❌ Nothing to update: provide a new title and/or content."
            if content is not None:
                content = content.strip()
                if not content:
                    return "❌ Failed to update memory: content is empty."

            result = await knowledge.update_memory(
                memory_id, title=title, content=content, campaign_id=campaign_id,
            )
            if result is None:
                return f"❌ No memory with id={memory_id} in campaign {campaign_id}."
            logger.info(
                f"✏️ [campaign_admin] Updated NPC memory '{result['title']}' "
                f"(id={memory_id}, campaign {campaign_id})"
            )
            return f"✅ Updated memory '{result['title']}' (id={memory_id}) in campaign {campaign_id}."
        except Exception as e:
            logger.exception(f"❌ [campaign_admin] Failed to update memory {memory_id}")
            return f"❌ Failed to update memory: {e}"

    @tool
    async def delete_npc_memory(memory_id: int) -> str:
        """Permanently delete an NPC memory by id. The memory must belong to
        an NPC in this campaign.
        """
        try:
            if not knowledge.delete_memory(memory_id, campaign_id=campaign_id):
                return f"❌ No memory with id={memory_id} in campaign {campaign_id}."
            logger.info(
                f"🗑️ [campaign_admin] Deleted NPC memory id={memory_id} (campaign {campaign_id})"
            )
            return f"✅ Deleted memory id={memory_id} from campaign {campaign_id}."
        except Exception as e:
            logger.exception(f"❌ [campaign_admin] Failed to delete memory {memory_id}")
            return f"❌ Failed to delete memory: {e}"

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
        update_participant_state,
        list_characters,
        add_npc_to_campaign,
        list_campaign_npcs,
        list_npc_memories,
        get_npc_memory,
        create_npc_memory,
        update_npc_memory,
        delete_npc_memory,
    ]
