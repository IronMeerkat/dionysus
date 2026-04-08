import asyncio
from datetime import datetime, timezone
from logging import getLogger

from langchain.tools import tool

from database.graphiti_utils import load_information, make_group_id
from database.graphiti_types import ENTITY_TYPES, EDGE_TYPES, EDGE_TYPE_MAP
from database.init_graphiti import graphiti
from database.models.world import LoreEntry, World
from database.postgres_connection import Session, session

from graphiti_core.nodes import EpisodeType

logger = getLogger(__name__)

RETRY_DELAYS = [5, 15, 45]


def _update_ingestion_status(entry_id: int, status: str) -> None:
    """Update the ingestion_status on a LoreEntry using a short-lived session."""
    db = Session()
    try:
        entry = db.query(LoreEntry).filter(LoreEntry.id == entry_id).first()
        if entry is not None:
            entry.ingestion_status = status
            db.commit()
            logger.info(f"📊 Updated ingestion_status for entry {entry_id} -> '{status}'")
        else:
            logger.warning(f"⚠️ Entry {entry_id} not found when updating ingestion_status")
    except Exception:
        logger.exception(f"❌ Failed to update ingestion_status for entry {entry_id}")
        db.rollback()
    finally:
        db.close()


def spawn_ingestion_task(
    entry_id: int,
    title: str,
    content: str,
    world_name: str,
    group_id: str,
) -> asyncio.Task[None]:
    """Fire-and-forget Graphiti ingestion with retry + status tracking.

    Returns the asyncio.Task so callers can optionally await it in tests.
    """

    async def _ingest_background() -> None:
        for attempt in range(len(RETRY_DELAYS) + 1):
            try:
                await graphiti.add_episode(
                    name=title,
                    episode_body=content,
                    source=EpisodeType.text,
                    source_description=f"lore_creator:{world_name}",
                    reference_time=datetime.now(timezone.utc),
                    group_id=group_id,
                    entity_types=ENTITY_TYPES,
                    edge_types=EDGE_TYPES,
                    edge_type_map=EDGE_TYPE_MAP,
                )
                _update_ingestion_status(entry_id, "ingested")
                logger.info(f"📜 Ingested '{title}' into Graphiti (group_id={group_id!r})")
                return
            except Exception:
                if attempt < len(RETRY_DELAYS):
                    delay = RETRY_DELAYS[attempt]
                    logger.warning(
                        f"⚠️ Graphiti ingestion attempt {attempt + 1} failed for '{title}', "
                        f"retrying in {delay}s..."
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.exception(
                        f"❌ Graphiti ingestion failed for '{title}' after "
                        f"{len(RETRY_DELAYS) + 1} attempts"
                    )
                    _update_ingestion_status(entry_id, "failed")

    return asyncio.create_task(_ingest_background())


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
async def save_lore_entry(title: str, content: str, world_name: str, category: str) -> str:
    """Save a new lore entry to both Postgres and the Graphiti knowledge graph.

    category should be one of: character, location, organization, nation,
    race, concept, creature, item, event, general.
    Only call this after the user has approved the draft.
    """
    try:
        world = World.get_or_create(world_name)

        entry = LoreEntry(
            world_id=world.id,
            title=title,
            content=content,
            category=category,
        )
        session.add(entry)
        session.commit()
        logger.info(f"📜 Saved LoreEntry '{title}' (id={entry.id}) to Postgres")

        spawn_ingestion_task(
            entry_id=entry.id,
            title=title,
            content=content,
            world_name=world_name,
            group_id=world.graphiti_group_id,
        )
        logger.info(f"📜 Postgres saved, Graphiti ingestion spawned in background for '{title}'")

        return (
            f"✅ Saved '{title}' (id={entry.id}) to world '{world_name}'. "
            "Knowledge graph ingestion is running in the background."
        )
    except Exception as e:
        logger.exception(f"❌ Failed to save lore entry '{title}'")
        session.rollback()
        return f"❌ Failed to save lore entry: {e}"


@tool
async def delete_lore_entry(entry_id: int, world_name: str) -> str:
    """Delete a lore entry from Postgres and clean up its Graphiti episodes.

    Looks up the entry by its Postgres ID and verifies it belongs to the
    named world before deleting.
    """
    try:
        entry = session.query(LoreEntry).filter(LoreEntry.id == entry_id).first()
        if entry is None:
            return f"❌ No lore entry found with id={entry_id}."

        if entry.world.name != world_name:
            return f"❌ Entry {entry_id} belongs to world '{entry.world.name}', not '{world_name}'."

        title = entry.title
        group_id = entry.world.graphiti_group_id

        episodes = await graphiti.retrieve_episodes(
            reference_time=datetime.now(timezone.utc),
            last_n=10_000,
            group_ids=[group_id],
        )
        deleted_episodes = 0
        for episode in episodes:
            if episode.name == title:
                await graphiti.remove_episode(episode.uuid)
                deleted_episodes += 1

        session.delete(entry)
        session.commit()
        logger.info(f"🗑️ Deleted LoreEntry '{title}' (id={entry_id}), removed {deleted_episodes} Graphiti episode(s)")

        return f"✅ Deleted '{title}' (id={entry_id}) and removed {deleted_episodes} associated episode(s) from the knowledge graph."
    except Exception as e:
        logger.exception(f"❌ Failed to delete lore entry {entry_id}")
        session.rollback()
        return f"❌ Failed to delete lore entry: {e}"
