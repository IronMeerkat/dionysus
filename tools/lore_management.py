import asyncio
from logging import getLogger

from langchain.tools import tool
from pydantic import BaseModel, Field

from database.graphiti_utils import load_information, make_group_id
from database.graphiti_types import ENTITY_TYPES
from database.neo4j_lore import create_entry, delete_entry, get_entry

logger = getLogger(__name__)


class LoreEntryInput(BaseModel):
    title: str = Field(description="Specific, standalone title for this entry")
    content: str = Field(description="The lore content, roughly 40-70 words")


@tool
async def search_lore(query: str, world_name: str) -> str:
    """Search existing lore in a world's knowledge graph.

    Use this to check what already exists before creating new entries,
    or to answer questions about the current state of the world's lore.
    """
    group_id = make_group_id("lore", world_name)
    results = await load_information(
        query=query,
        group_ids=[group_id],
        limit=15,
    )
    if not results:
        return f"🔍 No lore found for query '{query}' in world '{world_name}'."
    return results


@tool
async def search_entities(query: str, world_name: str, entity_type: str) -> str:
    """Search for specific entity types in the world's knowledge graph.

    entity_type must be one of: Character, Location, Organization, Nation,
    Race, Concept, Creature, Item, Event.
    """
    valid_types = set(ENTITY_TYPES.keys())
    if entity_type not in valid_types:
        return f"❌ Invalid entity_type '{entity_type}'. Must be one of: {', '.join(sorted(valid_types))}"

    group_id = make_group_id("lore", world_name)
    results = await load_information(
        query=query,
        group_ids=[group_id],
        node_labels=[entity_type],
        limit=15,
    )
    if not results:
        return f"🔍 No {entity_type} entities found for query '{query}' in world '{world_name}'."
    return results


@tool
async def save_lore_entry(title: str, content: str, world_name: str) -> str:
    """Save a single lore entry to the Neo4j knowledge graph.

    Call this once per atomic entry. When saving multiple entries from a
    larger article, call this tool separately for each one with its own
    title and content.
    """
    try:
        content = content.strip()
        if not content:
            return "❌ Failed to save lore entry: content is empty."

        entry = await create_entry(world_name, title, content)
        logger.info(f"📜 Saved '{title}' (uuid={entry['uuid']}) to world '{world_name}'")
        return f"✅ Saved '{entry['title']}' (uuid={entry['uuid']}) to world '{world_name}'."
    except Exception as e:
        logger.exception(f"❌ Failed to save lore entry '{title}'")
        return f"❌ Failed to save lore entry: {e}"


@tool
async def bulk_save_lore_entries(entries: list[LoreEntryInput], world_name: str) -> str:
    """Save many small lore entries to the knowledge graph in one call.

    Use this after the user approves a Wikipedia-style article and you have
    decomposed it into atomic entries. Each entry should have a specific
    standalone title and roughly 40-70 words of content.

    Saves run in the background so the conversation stays responsive.
    """
    valid = [e for e in entries if e.content.strip()]
    if not valid:
        return "❌ No entries to save: all content was empty."

    async def _save_all() -> None:
        succeeded = 0
        failed = 0
        for entry in valid:
            try:
                result = await create_entry(world_name, entry.title, entry.content.strip())
                logger.info(
                    f"📜 Bulk-saved '{entry.title}' (uuid={result['uuid']}) "
                    f"to world '{world_name}'"
                )
                succeeded += 1
            except Exception:
                logger.exception(f"❌ Bulk-save failed for '{entry.title}'")
                failed += 1

        logger.info(
            f"📦 Bulk save complete for world '{world_name}': "
            f"{succeeded} succeeded, {failed} failed out of {len(valid)}"
        )

    asyncio.create_task(_save_all())

    titles = ", ".join(f"'{e.title}'" for e in valid)
    return (
        f"📦 Queued {len(valid)} lore entries for background save to world "
        f"'{world_name}': {titles}. They will be ingested into the knowledge "
        "graph shortly."
    )


@tool
async def delete_lore_entry(episode_uuid: str, world_name: str) -> str:
    """Delete a lore entry from the Neo4j knowledge graph by episode UUID.

    Verifies the entry belongs to the named world before deleting.
    """
    try:
        entry = await get_entry(episode_uuid)
        if entry is None:
            return f"❌ No lore entry found with uuid={episode_uuid}."

        if entry["world_name"] != world_name:
            return (
                f"❌ Entry {episode_uuid} belongs to world '{entry['world_name']}', "
                f"not '{world_name}'."
            )

        deleted = await delete_entry(episode_uuid)
        if not deleted:
            return f"❌ Failed to delete entry {episode_uuid}."

        logger.info(f"🗑️ Deleted lore entry '{entry['title']}' (uuid={episode_uuid})")
        return f"✅ Deleted '{entry['title']}' (uuid={episode_uuid}) from world '{world_name}'."
    except Exception as e:
        logger.exception(f"❌ Failed to delete lore entry {episode_uuid}")
        return f"❌ Failed to delete lore entry: {e}"
