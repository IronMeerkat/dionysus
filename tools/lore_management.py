import re
from logging import getLogger

from langchain.tools import tool

from database.graphiti_utils import load_information, make_group_id
from database.graphiti_types import ENTITY_TYPES
from database.neo4j_lore import create_entry, delete_entry, get_entry

logger = getLogger(__name__)

TARGET_ENTRY_MIN_WORDS = 40
TARGET_ENTRY_MAX_WORDS = 70


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
    """Save a new lore entry directly to the Neo4j knowledge graph.

    Only call this after the user has approved the draft.
    """
    try:
        chunks = _split_lore_content(content)
        if not chunks:
            return "❌ Failed to save lore entry: content is empty after normalization."

        should_suffix_titles = len(chunks) > 1
        created: list[dict[str, object]] = []
        for idx, chunk in enumerate(chunks, start=1):
            chunk_title = f"{title} (Part {idx})" if should_suffix_titles else title
            entry = await create_entry(world_name, chunk_title, chunk)
            created.append(entry)

        logger.info(
            f"📜 Saved {len(created)} episode(s) for '{title}' in world '{world_name}'"
        )

        if len(created) == 1:
            ep = created[0]
            return (
                f"✅ Saved '{ep['title']}' (uuid={ep['uuid']}) to world '{world_name}'."
            )

        summaries = ", ".join([f"{e['uuid']}:{e['title']}" for e in created])
        return (
            f"✅ Saved {len(created)} lore entries for '{title}' in world "
            f"'{world_name}': {summaries}."
        )
    except Exception as e:
        logger.exception(f"❌ Failed to save lore entry '{title}'")
        return f"❌ Failed to save lore entry: {e}"


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
