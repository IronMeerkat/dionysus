"""Deterministic helpers for permanent character-sheet status effects.

Permanent effects live on the character (``CharacterStatusEffect``) and
travel across campaigns; temporary campaign-scoped conditions live in
``CampaignParticipant.state`` (see ``tools/participants.py``). This module
owns the CRUD, prompt rendering, and the deterministic presence-based
negation filter ("Natsumi's Autism is negated while Reiko is in the scene").
No LLM ever writes these rows directly -- builder agents go through the
LangChain tools below, the DM graph only reads.
"""
from logging import getLogger

from langchain.tools import tool

from database.models import Character, CharacterStatusEffect
from database.postgres_connection import session
from tools.dice import ADVANTAGE_STATES

logger = getLogger(__name__)


# ------------------------------------------------------------------
# Lookups + CRUD
# ------------------------------------------------------------------

def get_character_status_effects(character_id: int) -> list[CharacterStatusEffect]:
    """🧬 Fetch a character's permanent status effects, ordered by name."""
    return (
        session.query(CharacterStatusEffect)
        .filter(CharacterStatusEffect.character_id == character_id)
        .order_by(CharacterStatusEffect.name)
        .all()
    )


def upsert_character_status_effect(
    character_name: str,
    *,
    name: str,
    description: str = "",
    affects: str = "",
    roll_modifier: int = 0,
    advantage: str = "normal",
    negated_by: list[str] | None = None,
    negation_condition: str | None = None,
) -> CharacterStatusEffect | None:
    """🧬 Create or update one permanent status effect by (character, name).

    Matching is case-insensitive so builders don't fork an effect by
    re-casing its name. Returns the row, or None when the character or the
    advantage value is invalid.
    """
    character = session.query(Character).filter(Character.name == character_name.strip()).first()
    if character is None:
        logger.warning(f"⚠️ Status effect upsert skipped: no character named '{character_name}'")
        return None
    if advantage not in ADVANTAGE_STATES:
        logger.warning(f"⚠️ Status effect '{name}': unknown advantage '{advantage}'")
        return None

    clean_names = [n.strip() for n in (negated_by or []) if n.strip()]
    existing = next(
        (e for e in character.status_effects if e.name.lower() == name.strip().lower()),
        None,
    )
    if existing is None:
        existing = CharacterStatusEffect(character_id=character.id, name=name.strip())
        character.status_effects.append(existing)
        logger.info(f"🧬 Creating status effect '{name}' for '{character.name}'")
    else:
        logger.info(f"🧬 Updating status effect '{existing.name}' for '{character.name}'")

    existing.description = description.strip()
    existing.affects = affects.strip()
    existing.roll_modifier = roll_modifier
    existing.advantage = advantage
    existing.negated_by = clean_names
    existing.negation_condition = negation_condition.strip() if negation_condition else None
    session.commit()
    return existing


def delete_character_status_effect(character_name: str, name: str) -> bool:
    """🗑️ Remove one permanent status effect by (character, name)."""
    character = session.query(Character).filter(Character.name == character_name.strip()).first()
    if character is None:
        logger.warning(f"⚠️ Status effect delete skipped: no character named '{character_name}'")
        return False
    existing = next(
        (e for e in character.status_effects if e.name.lower() == name.strip().lower()),
        None,
    )
    if existing is None:
        logger.warning(f"⚠️ Status effect '{name}' not found on '{character.name}'")
        return False
    session.delete(existing)
    session.commit()
    logger.info(f"🗑️ Deleted status effect '{name}' from '{character.name}'")
    return True


# ------------------------------------------------------------------
# Rendering
# ------------------------------------------------------------------

def _render_effect(effect: CharacterStatusEffect) -> str:
    """One prompt-ready line describing an effect and its mechanics."""
    parts = [f"**{effect.name}**"]
    if effect.description:
        parts.append(effect.description)
    if effect.affects:
        parts.append(f"affects: {effect.affects}")
    mechanics = []
    if effect.roll_modifier:
        mechanics.append(f"{effect.roll_modifier:+d} to the roll")
    if effect.advantage and effect.advantage != "normal":
        mechanics.append(effect.advantage)
    if mechanics:
        parts.append("roll: " + ", ".join(mechanics))
    negation = []
    if effect.negated_by:
        negation.append("negated while present: " + ", ".join(effect.negated_by))
    if effect.negation_condition:
        negation.append(f"negated when: {effect.negation_condition}")
    if negation:
        parts.append("; ".join(negation))
    return "- " + " | ".join(parts)


def render_character_status_effects(character: Character) -> str:
    """🧬 Render a character's permanent effects as a prompt block.

    Returns an empty string when the sheet has none, so callers can append
    the block unconditionally.
    """
    if not character.status_effects:
        return ""
    lines = [f"Permanent status effects ({character.name}):"]
    lines.extend(_render_effect(e) for e in character.status_effects)
    return "\n".join(lines)


def character_sheet(character: Character) -> str:
    """📜 The character card with its permanent status effects appended.

    Drop-in replacement for ``character.description`` in prompts so every
    agent that reads a card also sees the character's roll mechanics.
    """
    description = character.description or ""
    effects = render_character_status_effects(character)
    return f"{description}\n\n{effects}" if effects else description


def active_status_effects(
    character: Character,
    present_names: list[str],
) -> list[CharacterStatusEffect]:
    """🚫 Deterministic negation filter: drop effects negated by presence.

    An effect whose ``negated_by`` names anyone currently in the scene does
    not apply this turn. Matching is case-insensitive; names come from the
    conversation's character roster.
    """
    present = {n.strip().lower() for n in present_names}
    return [
        e for e in character.status_effects
        if not {n.strip().lower() for n in (e.negated_by or [])} & present
    ]


def render_active_status_effects(character: Character, present_names: list[str]) -> str:
    """🧬 Render only the effects that apply right now (none negated).

    Negated effects are omitted entirely so the DM planner never sees --
    and therefore never applies -- them. Returns an empty string when
    nothing is active.
    """
    active = active_status_effects(character, present_names)
    if not active:
        return ""
    lines = [f"Active permanent status effects ({character.name}):"]
    lines.extend(_render_effect(e) for e in active)
    return "\n".join(lines)


# ------------------------------------------------------------------
# Agent tools (builders manage sheets through these)
# ------------------------------------------------------------------

@tool
def list_character_status_effects(character_name: str) -> str:
    """List a character's permanent status effects with their roll mechanics.

    Permanent effects live on the character sheet and apply in every
    campaign; use read_character for the narrative card. Returns an error
    message (never an exception) when the character is unknown.
    """
    character = session.query(Character).filter(Character.name == character_name.strip()).first()
    if character is None:
        logger.warning(f"⚠️ list_character_status_effects: no character named '{character_name}'")
        return f"❌ No character named '{character_name.strip()}'. Use list_characters to see who exists."
    if not character.status_effects:
        return f"🔍 '{character.name}' has no permanent status effects."
    logger.info(f"🧬 Listed {len(character.status_effects)} status effect(s) for '{character.name}'")
    return render_character_status_effects(character)


@tool
def set_character_status_effect(
    character_name: str,
    name: str,
    description: str = "",
    affects: str = "",
    roll_modifier: int = 0,
    advantage: str = "normal",
    negated_by: list[str] | None = None,
    negation_condition: str | None = None,
) -> str:
    """Create or update a permanent status effect on a character's sheet.

    - affects: which rolls the effect modifies, in plain words
      (e.g. "social gambits, Charisma checks"). The DM uses this to decide
      when the effect applies.
    - roll_modifier: flat bonus/penalty to those rolls (0 for none).
    - advantage: "advantage" | "normal" | "disadvantage" on those rolls.
    - negated_by: exact names of characters whose PRESENCE in the scene
      negates this effect (e.g. ["Reiko"]).
    - negation_condition: freeform extra condition that negates the effect
      (e.g. "when she wears her headphones").

    Upserts by (character, name): calling again with the same name updates.
    Returns an error message (never an exception) on unknown characters or
    invalid advantage values.
    """
    effect = upsert_character_status_effect(
        character_name,
        name=name,
        description=description,
        affects=affects,
        roll_modifier=roll_modifier,
        advantage=advantage,
        negated_by=negated_by,
        negation_condition=negation_condition,
    )
    if effect is None:
        return (
            f"❌ Could not set status effect '{name}' on '{character_name.strip()}'. "
            "Check the character name (use list_characters) and that advantage is "
            "one of: advantage, normal, disadvantage."
        )
    return f"✅ Status effect saved:\n{_render_effect(effect)}"


@tool
def remove_character_status_effect(character_name: str, name: str) -> str:
    """Remove a permanent status effect from a character's sheet by name.

    Returns an error message (never an exception) when the character or the
    effect is unknown.
    """
    if delete_character_status_effect(character_name, name):
        return f"✅ Removed status effect '{name.strip()}' from '{character_name.strip()}'."
    return (
        f"❌ No status effect '{name.strip()}' on '{character_name.strip()}'. "
        "Use list_character_status_effects to see what exists."
    )
