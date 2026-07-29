from logging import getLogger

from langchain.tools import tool

from database.models import (
    Campaign,
    CampaignParticipant,
)
from database.models import Character as CharacterModel
from database.models import World
from database.postgres_connection import session
from tools.status_effects import character_sheet

logger = getLogger(__name__)


def _world_participant_campaigns(world_name: str) -> dict[int, list[str]] | None:
    """Map character id -> campaign names for campaigns of the named world.

    Returns None when the world doesn't exist, so callers can still list
    globally without annotations instead of failing.
    """
    world = session.query(World).filter(World.name == world_name).first()
    if world is None:
        return None
    rows = (
        session.query(CampaignParticipant.character_id, Campaign.name)
        .join(Campaign, Campaign.id == CampaignParticipant.campaign_id)
        .filter(Campaign.world_id == world.id)
        .all()
    )
    membership: dict[int, list[str]] = {}
    for participant_id, campaign_name in rows:
        membership.setdefault(participant_id, []).append(campaign_name)
    return membership


def _render_roster(names: list[str], membership: dict[int, list[str]] | None, ids: list[int], kind: str) -> str:
    if not names:
        return f"🔍 No {kind} exist yet."
    lines = []
    for name, row_id in zip(names, ids):
        if membership is None:
            lines.append(f"- {name}")
        elif row_id in membership:
            campaigns = ", ".join(sorted(membership[row_id]))
            lines.append(f"- {name} -- in this world (campaigns: {campaigns})")
        else:
            lines.append(f"- {name}")
    return "\n".join(lines)


@tool
def check_npc_existence(npc_name: str) -> bool:
    """Check if an NPC exists in the database."""
    return CharacterModel.exists(name=npc_name)


@tool
def list_characters(world_name: str) -> str:
    """List every character in the database, one per line.

    Any character can be played or run as an NPC. Characters are shared
    across worlds; those participating in a campaign of the named world are
    annotated with the campaign names so you can tell the world's cast apart
    from everyone else. Use read_character with a name to fetch the full
    character card.
    """
    membership = _world_participant_campaigns(world_name)
    if membership is None:
        logger.warning(f"⚠️ World '{world_name}' not found; listing characters unannotated")
    characters = session.query(CharacterModel).order_by(CharacterModel.name).all()
    roster = _render_roster(
        [c.name for c in characters], membership, [c.id for c in characters], "characters",
    )
    logger.info(f"📋 Listed {len(characters)} characters for world '{world_name}'")
    return roster


@tool
def read_character(name: str) -> str:
    """Read the full current description of a character by name.

    Use list_characters first to discover who exists. Returns an error
    message (never an exception) when the name is unknown.
    """
    character = session.query(CharacterModel).filter(CharacterModel.name == name).first()
    if character is None:
        logger.warning(f"⚠️ read_character: no character named '{name}'")
        return f"❌ No character named '{name}'. Use list_characters to see who exists."
    description = character.description
    if description is None:
        return f"⚠️ Character '{name}' exists but has no description yet."
    logger.info(f"📖 Read character '{name}' (description v{character.description_version})")
    return f"# {character.name}\n\n{character_sheet(character)}"


@tool
def create_character(name: str, description: str) -> str:
    """Create a new character in the database.

    Names are globally unique: check list_characters first, and never reuse an
    existing character's name. Returns an error message (never an exception)
    when the name is taken or the write fails.
    """
    if CharacterModel.exists(name=name):
        logger.warning(f"⚠️ create_character refused duplicate name '{name}'")
        return (
            f"❌ A character named '{name}' already exists. "
            "Pick a different name, or use read_character to review the existing character first."
        )
    try:
        character = CharacterModel(name=name)
        session.add(character)
        session.flush()  # Get id before adding description
        character.add_description(description)
        session.commit()
    except Exception as e:
        session.rollback()
        logger.exception(f"❌ Failed to create character '{name}'")
        return f"❌ Failed to create character '{name}': {e}"
    logger.info(f"🎭 Created character '{name}'")
    return f"✅ Character '{name}' created."
