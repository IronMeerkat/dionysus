from logging import getLogger

from langchain.tools import tool

from database.models import Character as CharacterModel
from database.postgres_connection import session

logger = getLogger(__name__)


@tool
def check_npc_existence(npc_name: str) -> bool:
    """Check if an NPC exists in the database."""
    return CharacterModel.exists(name=npc_name)


@tool
def create_character(name: str, description: str) -> bool:
    """Create a new character in the database."""
    character = CharacterModel(name=name)
    session.add(character)
    session.flush()  # Get id before adding description
    character.add_description(description)
    session.commit()
    logger.info(f"🎭 Created character '{name}'")
    return True
