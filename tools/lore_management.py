import asyncio
from logging import getLogger

from langchain.tools import tool
from pydantic import BaseModel, Field

from database.graphiti_utils import load_information, make_group_id
from database.graphiti_types import ENTITY_TYPES
from database.graphiti_worlds import (
    create_entry,
    delete_entry,
    get_entry,
    list_entries,
    lore_group_id,
    update_entry,
)

from hephaestus.settings import settings

info_limits = settings.graphiti.information_limits

logger = getLogger(__name__)

# Max entries saved concurrently by bulk_save_lore_entries. Each save triggers
# a graphiti add_episode (LLM extraction + Neo4j writes), so this caps how many
# run in flight at once.
BULK_SAVE_CONCURRENCY = 20


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
        limit=info_limits.lore,
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
        limit=info_limits.lore,
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

        gid = lore_group_id(world_name)
        entry = await create_entry(gid, title, content, source_description=f"lore_creator:{world_name}")
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
        sem = asyncio.Semaphore(BULK_SAVE_CONCURRENCY)

        async def _save_one(entry: LoreEntryInput) -> bool:
            async with sem:
                try:
                    gid = lore_group_id(world_name)
                    result = await create_entry(
                        gid,
                        entry.title,
                        entry.content.strip(),
                        source_description=f"lore_creator:{world_name}",
                    )
                    logger.info(
                        f"📜 Bulk-saved '{entry.title}' (uuid={result['uuid']}) "
                        f"to world '{world_name}'"
                    )
                    return True
                except Exception:
                    logger.exception(f"❌ Bulk-save failed for '{entry.title}'")
                    return False

        results = await asyncio.gather(*[_save_one(e) for e in valid])
        succeeded = sum(1 for r in results if r)
        failed = len(results) - succeeded
        logger.info(
            f"📦 Bulk save complete for world '{world_name}': "
            f"{succeeded} succeeded, {failed} failed out of {len(valid)} "
            f"(concurrency={BULK_SAVE_CONCURRENCY})"
        )

    asyncio.create_task(_save_all())

    titles = ", ".join(f"'{e.title}'" for e in valid)
    return (
        f"📦 Queued {len(valid)} lore entries for background save to world "
        f"'{world_name}': {titles}. They will be ingested into the knowledge "
        "graph shortly."
    )


@tool
async def list_lore_entries(world_name: str) -> str:
    """List all lore entries stored in a world's knowledge graph.

    Returns each entry's UUID, title, and creation time, one per line. Use
    this to discover the UUIDs you need to modify or delete an entry. To see
    the full content of a single entry, use search_lore with the entry's
    title as the query.
    """
    gid = lore_group_id(world_name)
    entries = await list_entries(gid)
    if not entries:
        return f"🔍 No lore entries found in world '{world_name}'."
    lines = [
        f"- uuid={e['uuid']} | title='{e['title']}' | created_at={e['created_at']}"
        for e in entries
    ]
    logger.info(f"📋 Listed {len(entries)} lore entries in world '{world_name}'")
    return "\n".join(lines)


@tool
async def update_lore_entry(
    episode_uuid: str,
    world_name: str,
    title: str | None = None,
    content: str | None = None,
) -> str:
    """Modify an existing lore entry's title and/or content.

    Provide only the field(s) you want to change; the other is preserved.
    Updating re-creates the entry (Graphiti assigns a new UUID), so
    subsequent references should use the UUID returned here.

    Verifies the entry belongs to the named world before updating.
    """
    try:
        existing = await get_entry(episode_uuid)
        if existing is None:
            return f"❌ No lore entry found with uuid={episode_uuid}."

        expected_gid = lore_group_id(world_name)
        if existing["group_id"] != expected_gid:
            return (
                f"❌ Entry {episode_uuid} does not belong to world '{world_name}'."
            )

        if title is None and content is None:
            return "❌ Nothing to update: provide a new title and/or content."

        if content is not None:
            content = content.strip()
            if not content:
                return "❌ Failed to update lore entry: content is empty."

        updated = await update_entry(episode_uuid, title=title, content=content)
        if updated is None:
            return f"❌ Failed to update entry {episode_uuid}."

        logger.info(
            f"✏️ Updated lore entry in world '{world_name}': "
            f"'{existing['title']}' (uuid={episode_uuid}) -> "
            f"'{updated['title']}' (uuid={updated['uuid']})"
        )
        return (
            f"✅ Updated '{updated['title']}' (new uuid={updated['uuid']}) "
            f"in world '{world_name}'. The old uuid={episode_uuid} no longer exists."
        )
    except Exception as e:
        logger.exception(f"❌ Failed to update lore entry {episode_uuid}")
        return f"❌ Failed to update lore entry: {e}"


@tool
async def delete_lore_entry(episode_uuid: str, world_name: str) -> str:
    """Delete a lore entry from the Neo4j knowledge graph by episode UUID.

    Verifies the entry belongs to the named world before deleting.
    """
    try:
        entry = await get_entry(episode_uuid)
        if entry is None:
            return f"❌ No lore entry found with uuid={episode_uuid}."

        expected_gid = lore_group_id(world_name)
        if entry["group_id"] != expected_gid:
            return (
                f"❌ Entry {episode_uuid} does not belong to world '{world_name}'."
            )

        deleted = await delete_entry(episode_uuid)
        if not deleted:
            return f"❌ Failed to delete entry {episode_uuid}."

        logger.info(f"🗑️ Deleted lore entry '{entry['title']}' (uuid={episode_uuid})")
        return f"✅ Deleted '{entry['title']}' (uuid={episode_uuid}) from world '{world_name}'."
    except Exception as e:
        logger.exception(f"❌ Failed to delete lore entry {episode_uuid}")
        return f"❌ Failed to delete lore entry: {e}"
