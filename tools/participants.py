"""Deterministic participant-state helpers: campaign-scoped player/NPC vitals.

Layer-1 deterministic functions ("narrator decorates, canon decides"): the DM
planner produces structured ``ParticipantStateUpdate`` patches, and these
helpers resolve them to a (campaign, participant) row and apply them to
Postgres with validation and audit logging. No LLM ever writes state directly.

The mechanical state itself is a freeform JSONB blob (see
``CampaignPlayer`` / ``CampaignNPC``); these helpers only standardise the
well-known sub-keys (stats / status_effects / modifiers / notes) and render
them prompt-ready. Any other keys are preserved and rendered generically.
"""
from logging import getLogger
from typing import Any

import json

from database.models import CampaignNPC, CampaignPlayer, Character, Player
from database.models.participants import DEFAULT_PARTICIPANT_STATE
from database.postgres_connection import session

logger = getLogger(__name__)


# ------------------------------------------------------------------
# Lookups + ensure
# ------------------------------------------------------------------

def get_campaign_player(campaign_id: int, player_id: int) -> CampaignPlayer | None:
    """🎲 Fetch a player's campaign state row, or None."""
    return (
        session.query(CampaignPlayer)
        .filter(
            CampaignPlayer.campaign_id == campaign_id,
            CampaignPlayer.player_id == player_id,
        )
        .first()
    )


def ensure_campaign_player(campaign_id: int, player_id: int) -> CampaignPlayer:
    """🎲 Get a player's campaign state row, creating an empty one if missing."""
    row = get_campaign_player(campaign_id, player_id)
    if row is not None:
        return row
    row = CampaignPlayer(campaign_id=campaign_id, player_id=player_id)
    session.add(row)
    session.commit()
    logger.info(f"🎲 Created campaign_players row (campaign {campaign_id}, player {player_id})")
    return row


def get_campaign_npc(campaign_id: int, character_id: int) -> CampaignNPC | None:
    """🎭 Fetch an NPC's campaign state row, or None."""
    return (
        session.query(CampaignNPC)
        .filter(
            CampaignNPC.campaign_id == campaign_id,
            CampaignNPC.character_id == character_id,
        )
        .first()
    )


def ensure_campaign_npc(campaign_id: int, character_id: int) -> CampaignNPC:
    """🎭 Get an NPC's campaign state row, creating an empty one if missing."""
    row = get_campaign_npc(campaign_id, character_id)
    if row is not None:
        return row
    row = CampaignNPC(campaign_id=campaign_id, character_id=character_id)
    session.add(row)
    session.commit()
    logger.info(f"🎭 Created campaign_npcs row (campaign {campaign_id}, character {character_id})")
    return row


# ------------------------------------------------------------------
# Rendering
# ------------------------------------------------------------------

def _format_value(value: Any) -> str:
    """Pretty-print a scalar for the prompt block."""
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def _render_state_blob(state: dict | None) -> str:
    """Render a participant's state blob as a compact, prompt-ready block.

    Unknown top-level keys are rendered generically so campaigns can track
    bespoke variables without code changes.
    """
    state = state or {}
    if not state or all(
        (not state.get(k) if isinstance(state.get(k), (list, dict, str)) else False)
        for k in state
    ):
        return "(no tracked mechanical state)"

    lines: list[str] = []
    stats = state.get("stats")
    if isinstance(stats, dict) and stats:
        joined = ", ".join(f"{k}={_format_value(v)}" for k, v in stats.items())
        lines.append(f"stats: {joined}")

    effects = state.get("status_effects")
    if isinstance(effects, list) and effects:
        lines.append("status: " + ", ".join(str(e) for e in effects))

    modifiers = state.get("modifiers")
    if isinstance(modifiers, dict) and modifiers:
        parts = []
        for k, v in modifiers.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                parts.append(f"{k}{'+' if v >= 0 else ''}{v}")
            else:
                parts.append(f"{k}={_format_value(v)}")
        lines.append("modifiers: " + ", ".join(parts))

    notes = state.get("notes")
    if isinstance(notes, str) and notes.strip():
        lines.append(f"notes: {notes.strip()}")

    # Render any bespoke top-level keys not covered above.
    known = {"stats", "status_effects", "modifiers", "notes"}
    for key, value in state.items():
        if key in known:
            continue
        if value is None or value == "" or value == [] or value == {}:
            continue
        if isinstance(value, (list, dict)):
            lines.append(f"{key}: {json.dumps(value)}")
        else:
            lines.append(f"{key}: {_format_value(value)}")

    return "\n".join(lines) if lines else "(no tracked mechanical state)"


def render_player_state(campaign_id: int, player_id: int) -> str:
    """🎲 Render the player's live mechanical state as a prompt block."""
    row = ensure_campaign_player(campaign_id, player_id)
    return _render_state_blob(row.state)


def render_npc_state(campaign_id: int, character_id: int, name: str) -> str:
    """🎭 Render a single NPC's live mechanical state under its name."""
    row = ensure_campaign_npc(campaign_id, character_id)
    blob = _render_state_blob(row.state)
    if blob == "(no tracked mechanical state)":
        return f"**{name}**: {blob}"
    return f"**{name}**:\n{blob}"


def render_npc_states(campaign_id: int, characters: list[Character]) -> str:
    """🎭 Render all active NPCs' mechanical state as one prompt block."""
    if not characters:
        return "(no NPCs in scene)"
    blocks = [render_npc_state(campaign_id, c.id, c.name) for c in characters]
    if all("(no tracked mechanical state)" in b for b in blocks):
        return "(no tracked mechanical state for active NPCs)"
    return "\n\n".join(blocks)


# ------------------------------------------------------------------
# Patch application (called by the canon manager)
# ------------------------------------------------------------------

def _normalise_state(state: dict | None) -> dict:
    """Ensure the well-known sub-keys exist, preserving everything else."""
    state = dict(state or {})
    state.setdefault("stats", {})
    state.setdefault("status_effects", [])
    state.setdefault("modifiers", {})
    state.setdefault("notes", "")
    return state


def _resolve_participant(campaign_id: int, name: str, role: str) -> CampaignPlayer | CampaignNPC | None:
    """Find the campaign state row for a named participant, or None."""
    if role == "player":
        player = session.query(Player).filter(Player.name == name).first()
        if player is None:
            return None
        return ensure_campaign_player(campaign_id, player.id)
    if role == "npc":
        character = session.query(Character).filter(Character.name == name).first()
        if character is None:
            return None
        return ensure_campaign_npc(campaign_id, character.id)
    return None


def apply_participant_state_update(
    campaign_id: int,
    *,
    name: str,
    role: str,
    stats_set: dict[str, int] | None = None,
    status_added: list[str] | None = None,
    status_removed: list[str] | None = None,
    modifiers_set: dict[str, int] | None = None,
    notes: str | None = None,
) -> CampaignPlayer | CampaignNPC | None:
    """🎲🎭 Apply a structured patch to a participant's live state.

    Stats and modifiers are merged by key (overwrite); status effects are
    added/removed with case-insensitive set semantics; notes are replaced when
    provided. The blob is reassigned so SQLAlchemy persists the JSONB change.
    Returns the updated row, or None if the participant could not be resolved.
    """
    row = _resolve_participant(campaign_id, name.strip(), role.strip().lower())
    if row is None:
        logger.warning(f"⚠️ Participant state update skipped: no {role} named '{name}' in campaign {campaign_id}")
        return None

    state = _normalise_state(row.state)
    changed = False

    for key, value in (stats_set or {}).items():
        state["stats"][key] = value
        changed = True

    effects = [str(e).strip() for e in (state["status_effects"] or []) if str(e).strip()]
    lower_existing = {e.lower(): e for e in effects}
    for add in (status_added or []):
        add = add.strip()
        if add and add.lower() not in lower_existing:
            effects.append(add)
            lower_existing[add.lower()] = add
            changed = True
    for rem in (status_removed or []):
        rem = rem.strip().lower()
        if rem and rem in lower_existing:
            effects = [e for e in effects if e.lower() != rem]
            del lower_existing[rem]
            changed = True
    state["status_effects"] = effects

    for key, value in (modifiers_set or {}).items():
        state["modifiers"][key] = value
        changed = True

    if notes is not None:
        state["notes"] = notes
        changed = True

    if not changed:
        logger.info(f"📋 Participant state update for '{name}' ({role}) was empty, nothing changed")
        return row

    row.state = state
    session.add(row)
    session.commit()
    logger.info(f"📋 Updated {role} '{name}' state in campaign {campaign_id}: {state}")
    return row
