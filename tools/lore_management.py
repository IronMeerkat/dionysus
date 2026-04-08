import asyncio
from datetime import datetime, timezone
from logging import getLogger
import re

from langchain.tools import tool

from database.graphiti_utils import load_information, make_group_id
from database.graphiti_types import ENTITY_TYPES, EDGE_TYPES, EDGE_TYPE_MAP
from database.init_graphiti import graphiti
from database.models.world import LoreEntry, World
from database.postgres_connection import Session, session

from graphiti_core.nodes import EpisodeType

logger = getLogger(__name__)

RETRY_DELAYS = [5, 15, 45]
TARGET_ENTRY_MIN_WORDS = 120
TARGET_ENTRY_MAX_WORDS = 250


def _word_count(text: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", text))


def _split_paragraph_into_sentence_chunks(paragraph: str) -> list[str]:
    """Split a long paragraph into sentence-aware chunks near target size."""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", paragraph.strip()) if s.strip()]
    if not sentences:
        return []

    chunks: list[str] = []
    current: list[str] = []
    current_words = 0

    for sentence in sentences:
        sentence_words = _word_count(sentence)
        would_exceed = current and (current_words + sentence_words > TARGET_ENTRY_MAX_WORDS)
        if would_exceed:
            chunks.append(" ".join(current).strip())
            current = [sentence]
            current_words = sentence_words
            continue

        current.append(sentence)
        current_words += sentence_words

    if current:
        chunks.append(" ".join(current).strip())
    return chunks


def _split_lore_content(content: str) -> list[str]:
    """Create coherent lore chunks using paragraph-first, sentence-second splitting."""
    normalized_content = content.strip()
    if not normalized_content:
        return []

    if _word_count(normalized_content) <= TARGET_ENTRY_MAX_WORDS:
        return [normalized_content]

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", normalized_content) if p.strip()]
    if not paragraphs:
        return [normalized_content]

    chunks: list[str] = []
    current_parts: list[str] = []
    current_words = 0

    def flush_current() -> None:
        nonlocal current_parts, current_words
        if current_parts:
            chunks.append("\n\n".join(current_parts).strip())
            current_parts = []
            current_words = 0

    for paragraph in paragraphs:
        paragraph_words = _word_count(paragraph)
        if paragraph_words > TARGET_ENTRY_MAX_WORDS:
            flush_current()
            sentence_chunks = _split_paragraph_into_sentence_chunks(paragraph)
            chunks.extend([chunk for chunk in sentence_chunks if chunk])
            continue

        would_exceed = current_parts and (current_words + paragraph_words > TARGET_ENTRY_MAX_WORDS)
        if would_exceed and current_words >= TARGET_ENTRY_MIN_WORDS:
            flush_current()

        current_parts.append(paragraph)
        current_words += paragraph_words

    flush_current()
    return [chunk for chunk in chunks if chunk]


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
        chunks = _split_lore_content(content)
        if not chunks:
            return "❌ Failed to save lore entry: content is empty after normalization."

        should_suffix_titles = len(chunks) > 1
        entries: list[LoreEntry] = []
        for idx, chunk in enumerate(chunks, start=1):
            chunk_title = f"{title} (Part {idx})" if should_suffix_titles else title
            entry = LoreEntry(
                world_id=world.id,
                title=chunk_title,
                content=chunk,
                category=category,
            )
            entries.append(entry)
            session.add(entry)

        session.commit()
        logger.info(
            f"📜 Saved {len(entries)} LoreEntry row(s) for '{title}' "
            f"in world '{world_name}'"
        )

        for entry in entries:
            spawn_ingestion_task(
                entry_id=entry.id,
                title=entry.title,
                content=entry.content,
                world_name=world_name,
                group_id=world.graphiti_group_id,
            )
        logger.info(
            f"📜 Postgres saved, spawned {len(entries)} Graphiti ingestion task(s) "
            f"for base title '{title}'"
        )

        if len(entries) == 1:
            entry = entries[0]
            return (
                f"✅ Saved '{entry.title}' (id={entry.id}) to world '{world_name}'. "
                "Knowledge graph ingestion is running in the background."
            )

        entry_summaries = ", ".join([f"{entry.id}:{entry.title}" for entry in entries])
        return (
            f"✅ Saved {len(entries)} lore entries for base title '{title}' in world "
            f"'{world_name}': {entry_summaries}. Knowledge graph ingestion is running "
            "in the background for each entry."
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
