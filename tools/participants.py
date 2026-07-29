"""Deterministic participant-state helpers: campaign-scoped character vitals.

Layer-1 deterministic functions ("narrator decorates, canon decides"): the DM
planner produces structured ``ParticipantStateUpdate`` patches, and these
helpers resolve them to a (campaign, character) row and apply them to
Postgres with validation and audit logging. No LLM ever writes state directly.

The mechanical state itself is a freeform JSONB blob (see
``CampaignParticipant``); these helpers only standardise the well-known
sub-keys (stats / status_effects / modifiers / notes) and render them
prompt-ready. Any other keys are preserved and rendered generically.

Players and NPCs share the same table: which character is the PC is a
conversation-level decision, so these helpers never distinguish by role.
"""
from logging import getLogger
from typing import Any

import json

from database.models import CampaignParticipant, Character
from database.models.participants import DEFAULT_PARTICIPANT_STATE
from database.postgres_connection import session

logger = getLogger(__name__)


# ------------------------------------------------------------------
# Lookups + ensure
# ------------------------------------------------------------------

def get_campaign_participant(campaign_id: int, character_id: int) -> CampaignParticipant | None:
    """🎲 Fetch a character's campaign state row, or None."""
    return (
        session.query(CampaignParticipant)
        .filter(
            CampaignParticipant.campaign_id == campaign_id,
            CampaignParticipant.character_id == character_id,
        )
        .first()
    )


def ensure_campaign_participant(campaign_id: int, character_id: int) -> CampaignParticipant:
    """🎲 Get a character's campaign state row, creating an empty one if missing."""
    row = get_campaign_participant(campaign_id, character_id)
    if row is not None:
        return row
    row = CampaignParticipant(campaign_id=campaign_id, character_id=character_id)
    session.add(row)
    session.commit()
    logger.info(f"🎲 Created campaign_participants row (campaign {campaign_id}, character {character_id})")
    return row


# ------------------------------------------------------------------
# Rendering
# ------------------------------------------------------------------

def _format_value(value: Any) -> str:
    """Pretty-print a scalar for the prompt block."""
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def _normalise_effect(entry: Any) -> dict:
    """Coerce a legacy string or partial dict into the effect shape.

    Status effects are stored sparsely: ``name`` plus only the mechanical
    keys that are actually set (note / affects / roll_modifier / advantage).
    Legacy plain-string entries become ``{"name": ...}``.
    """
    if isinstance(entry, str):
        return {"name": entry.strip()}
    if isinstance(entry, dict):
        out = {"name": str(entry.get("name", "")).strip()}
        for key in ("note", "affects", "roll_modifier", "advantage"):
            value = entry.get(key)
            if value is not None and value != "" and not (
                key == "roll_modifier" and value == 0
            ) and not (key == "advantage" and value == "normal"):
                out[key] = value
        return out
    logger.warning(f"⚠️ Unrecognised status effect entry {entry!r}, coercing to name")
    return {"name": str(entry)}


def _render_effect_entry(entry: dict) -> str:
    """Render one structured effect, e.g. ``poisoned (-2, affects: attacks; venom)``."""
    name = entry.get("name") or "?"
    mechanics = []
    modifier = entry.get("roll_modifier")
    if isinstance(modifier, (int, float)) and modifier:
        mechanics.append(f"{modifier:+d}")
    advantage = entry.get("advantage")
    if advantage and advantage != "normal":
        mechanics.append(str(advantage))
    mech = f" ({', '.join(mechanics)})" if mechanics else ""
    details = []
    if entry.get("affects"):
        details.append(f"affects: {entry['affects']}")
    if entry.get("note"):
        details.append(str(entry["note"]))
    suffix = f" [{'; '.join(details)}]" if details else ""
    return f"{name}{mech}{suffix}"


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
        lines.append(
            "status: " + ", ".join(_render_effect_entry(_normalise_effect(e)) for e in effects)
        )

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


def render_participant_state(campaign_id: int, character_id: int, name: str | None = None) -> str:
    """🎲 Render a single participant's live mechanical state as a prompt block.

    With no ``name`` the bare blob is returned (used for the PC block); with a
    name the blob is headed by ``**name**:`` (used for NPC rosters).
    """
    row = ensure_campaign_participant(campaign_id, character_id)
    blob = _render_state_blob(row.state)
    if name is None:
        return blob
    if blob == "(no tracked mechanical state)":
        return f"**{name}**: {blob}"
    return f"**{name}**:\n{blob}"


def render_participant_states(campaign_id: int, characters: list[Character]) -> str:
    """🎭 Render all given participants' mechanical state as one prompt block."""
    if not characters:
        return "(no NPCs in scene)"
    blocks = [render_participant_state(campaign_id, c.id, c.name) for c in characters]
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


def _resolve_participant(campaign_id: int, name: str) -> CampaignParticipant | None:
    """Find the campaign state row for a named character, or None."""
    character = session.query(Character).filter(Character.name == name).first()
    if character is None:
        return None
    return ensure_campaign_participant(campaign_id, character.id)


def apply_participant_state_update(
    campaign_id: int,
    *,
    name: str,
    stats_set: dict[str, int] | None = None,
    status_added: list[str | dict] | None = None,
    status_removed: list[str] | None = None,
    modifiers_set: dict[str, int] | None = None,
    notes: str | None = None,
) -> CampaignParticipant | None:
    """🎲 Apply a structured patch to a participant's live state.

    Stats and modifiers are merged by key (overwrite); notes are replaced
    when provided. Status effects are stored as sparse dicts
    ``{name, note?, affects?, roll_modifier?, advantage?}`` (legacy plain
    strings are normalised on write) with case-insensitive set semantics by
    name: adding an existing name merges any mechanical keys the patch
    carries. The blob is reassigned so SQLAlchemy persists the JSONB change.
    Returns the updated row, or None if the character could not be resolved.
    """
    row = _resolve_participant(campaign_id, name.strip())
    if row is None:
        logger.warning(f"⚠️ Participant state update skipped: no character named '{name}' in campaign {campaign_id}")
        return None

    state = _normalise_state(row.state)
    changed = False

    for key, value in (stats_set or {}).items():
        state["stats"][key] = value
        changed = True

    effects = [e for e in (_normalise_effect(x) for x in (state["status_effects"] or [])) if e["name"]]
    lower_existing = {e["name"].lower(): e for e in effects}
    for add in (status_added or []):
        entry = _normalise_effect(add)
        key = entry["name"].lower()
        if not key:
            continue
        if key in lower_existing:
            mechanics = {k: v for k, v in entry.items() if k != "name"}
            if mechanics:
                lower_existing[key].update(mechanics)
                changed = True
        else:
            effects.append(entry)
            lower_existing[key] = entry
            changed = True
    for rem in (status_removed or []):
        rem = rem.strip().lower()
        if rem and rem in lower_existing:
            effects = [e for e in effects if e["name"].lower() != rem]
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
        logger.info(f"📋 Participant state update for '{name}' was empty, nothing changed")
        return row

    row.state = state
    session.add(row)
    session.commit()
    logger.info(f"📋 Updated '{name}' state in campaign {campaign_id}: {state}")
    return row
