"""🧠📚 Knowledge persistence: the lore library, character memories, and the
campaign knowledge streams (world events, DM secrets, player preferences).

Single service module replacing the Graphiti store. Everything sync runs on
its own Session (a shared Session is not thread-safe, and these helpers are
called from asyncio.to_thread workers), and everything returned is a plain
dict -- no detached ORM instances leak across session boundaries.
"""
import asyncio
from contextlib import contextmanager
from logging import getLogger

from langchain_core.messages import AnyMessage
from langchain_ollama import OllamaEmbeddings
from sqlalchemy import func

from database.models import (
    CharacterMemory,
    DMSecret,
    LoreEntry,
    PlayerPreference,
    World,
    WorldEvent,
)
from database.postgres_connection import Session as SessionFactory
from hephaestus.settings import settings
from utils.llm_models import memory_filter
from utils.prompts import memory_significance_prompt

logger = getLogger(__name__)

NOTHING_MARKER = "NOTHING"

cfg = settings.memory
recall_cfg = cfg.recall

# Append-only campaign streams and how many recent rows the DM context gets.
STREAM_MODELS = (WorldEvent, DMSecret, PlayerPreference)
_STREAM_LIMITS = {
    WorldEvent: recall_cfg.events_recent,
    DMSecret: recall_cfg.secrets_recent,
    PlayerPreference: recall_cfg.prefs_recent,
}


@contextmanager
def _session():
    s = SessionFactory()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------

_embedder = OllamaEmbeddings(model=cfg.embed_model, num_gpu=cfg.num_gpu)


async def _embed_or_none(text: str) -> list[float] | None:
    """🔢 Embed into a ``settings.memory.embed_dim`` vector, or None on failure."""
    try:
        return await _embedder.aembed_query(text)
    except Exception:
        logger.exception("⚠️ Embedding failed; saving without vector")
        return None


# ---------------------------------------------------------------------------
# Worlds
# ---------------------------------------------------------------------------


def _world_dict(world: World, entry_count: int) -> dict[str, object]:
    return {
        "id": world.id,
        "name": world.name,
        "description": world.description,
        "entry_count": entry_count,
        "created_at": world.created_at.isoformat(),
    }


def list_worlds() -> list[dict[str, object]]:
    """🌍 All worlds, alphabetically, with entry counts (counted in SQL --
    entries are never loaded)."""
    with _session() as s:
        rows = (
            s.query(World, func.count(LoreEntry.id))
            .outerjoin(LoreEntry, LoreEntry.world_id == World.id)
            .group_by(World.id)
            .order_by(World.name)
            .all()
        )
        return [_world_dict(world, count) for world, count in rows]


def get_world_by_name(name: str) -> dict[str, object] | None:
    with _session() as s:
        world = s.query(World).filter(World.name == name).first()
        if world is None:
            return None
        count = s.query(func.count(LoreEntry.id)).filter(LoreEntry.world_id == world.id).scalar()
        return _world_dict(world, count)


def get_world_id(name: str) -> int | None:
    """🌍 Resolve a world name to its id -- single-column lookup for callers
    that don't need the full world payload."""
    with _session() as s:
        row = s.query(World.id).filter(World.name == name).first()
        return row[0] if row else None


def create_world(name: str, description: str = "") -> dict[str, object]:
    """🌍 Create a world row."""
    with _session() as s:
        world = World(name=name.strip(), description=description.strip())
        s.add(world)
        s.flush()
        logger.info(f"🌍 Created world '{world.name}' (id={world.id})")
        return _world_dict(world, entry_count=0)


def delete_world(world_id: int) -> int:
    """🗑️ Delete a world and its entries. Returns the number of entries removed."""
    with _session() as s:
        world = s.query(World).filter(World.id == world_id).first()
        if world is None:
            return 0
        count = (
            s.query(LoreEntry)
            .filter(LoreEntry.world_id == world_id)
            .delete(synchronize_session=False)
        )
        s.delete(world)
        logger.info(f"🗑️ Deleted world '{world.name}' (id={world_id}, {count} entries)")
        return count


# ---------------------------------------------------------------------------
# Lore entries (full markdown documents)
# ---------------------------------------------------------------------------


def _entry_dict(entry: LoreEntry) -> dict[str, object]:
    return {
        "id": entry.id,
        "title": entry.title,
        "content": entry.content,
        "world_name": entry.world.name,
        "created_at": entry.created_at.isoformat(),
        "updated_at": entry.updated_at.isoformat(),
    }


def list_entries(world_id: int) -> list[dict[str, object]]:
    """📋 All lore entries of a world (id, title, preview, timestamps), oldest first."""
    with _session() as s:
        entries = (
            s.query(LoreEntry)
            .filter(LoreEntry.world_id == world_id)
            .order_by(LoreEntry.created_at)
            .all()
        )
        return [
            {
                "id": e.id,
                "title": e.title,
                "preview": " ".join(e.content.split())[: recall_cfg.lore_preview_chars],
                "created_at": e.created_at.isoformat(),
                "updated_at": e.updated_at.isoformat(),
            }
            for e in entries
        ]


def _entry_filters(entry_id: int, world_id: int | None) -> list:
    filters = [LoreEntry.id == entry_id]
    if world_id is not None:
        filters.append(LoreEntry.world_id == world_id)
    return filters


def get_entry(entry_id: int, world_id: int | None = None) -> dict[str, object] | None:
    """📖 Fetch one entry; pass ``world_id`` to also require world ownership."""
    with _session() as s:
        entry = s.query(LoreEntry).filter(*_entry_filters(entry_id, world_id)).first()
        return _entry_dict(entry) if entry else None


def create_entry(world_id: int, title: str, content: str) -> dict[str, object]:
    """📜 Store a full-markdown lore entry."""
    with _session() as s:
        entry = LoreEntry(world_id=world_id, title=title.strip(), content=content.strip())
        s.add(entry)
        s.flush()
        logger.info(f"📜 Created lore entry '{entry.title}' (id={entry.id}, world_id={world_id})")
        return _entry_dict(entry)


def update_entry(
    entry_id: int,
    title: str | None = None,
    content: str | None = None,
    world_id: int | None = None,
) -> dict[str, object] | None:
    """✏️ Update an entry's title and/or content in place (stable id).
    Pass ``world_id`` to also require world ownership."""
    with _session() as s:
        entry = s.query(LoreEntry).filter(*_entry_filters(entry_id, world_id)).first()
        if entry is None:
            return None
        if title is not None:
            entry.title = title.strip()
        if content is not None:
            entry.content = content.strip()
        s.flush()
        logger.info(f"✏️ Updated lore entry '{entry.title}' (id={entry_id})")
        return _entry_dict(entry)


def delete_entry(entry_id: int, world_id: int | None = None) -> bool:
    """🗑️ Delete a single lore entry. Returns True if it existed.
    Pass ``world_id`` to also require world ownership."""
    with _session() as s:
        entry = s.query(LoreEntry).filter(*_entry_filters(entry_id, world_id)).first()
        if entry is None:
            return False
        s.delete(entry)
        logger.info(f"🗑️ Deleted lore entry '{entry.title}' (id={entry_id})")
        return True


# ---------------------------------------------------------------------------
# Character memories
# ---------------------------------------------------------------------------


def _memory_dict(memory: CharacterMemory) -> dict[str, object]:
    return {
        "id": memory.id,
        "campaign_id": memory.campaign_id,
        "character_id": memory.character_id,
        "title": memory.title,
        "content": memory.content,
        "created_at": memory.created_at.isoformat(),
    }


async def save_memory(
    campaign_id: int, character_id: int, title: str, content: str,
) -> dict[str, object]:
    """💾 Embed and store one character memory."""
    vector = await _embed_or_none(content)

    def _insert() -> dict[str, object]:
        with _session() as s:
            memory = CharacterMemory(
                campaign_id=campaign_id,
                character_id=character_id,
                title=title.strip(),
                content=content.strip(),
                embedding=vector,
            )
            s.add(memory)
            s.flush()
            return _memory_dict(memory)

    result = await asyncio.to_thread(_insert)
    logger.info(f"💾 Memory '{result['title']}' saved (id={result['id']}, campaign {campaign_id})")
    return result


async def recall_memories(campaign_id: int, character_id: int, query: str) -> str:
    """🔍 Recall an NPC's memories: pgvector top-K similar to *query* plus the
    most recent few, deduplicated, rendered newline-joined (oldest first)."""
    vector = await _embed_or_none(query)

    def _fetch() -> list[tuple[int, str]]:
        with _session() as s:
            base = s.query(CharacterMemory).filter(
                CharacterMemory.campaign_id == campaign_id,
                CharacterMemory.character_id == character_id,
            )
            similar: list[CharacterMemory] = []
            if vector is not None:
                similar = (
                    base.filter(CharacterMemory.embedding.isnot(None))
                    .order_by(CharacterMemory.embedding.cosine_distance(vector))
                    .limit(recall_cfg.memories_top_k)
                    .all()
                )
            recent = (
                base.order_by(CharacterMemory.id.desc())
                .limit(recall_cfg.memories_recent)
                .all()
            )
            seen: dict[int, str] = {m.id: m.content for m in similar}
            for m in recent:
                seen.setdefault(m.id, m.content)
            return sorted(seen.items())

    memories = await asyncio.to_thread(_fetch)
    logger.info(
        f"🧠 Recalled {len(memories)} memories for character {character_id} "
        f"(campaign {campaign_id})"
    )
    return "\n".join(content for _, content in memories)


async def process_and_save_memory(
    messages: list[AnyMessage],
    campaign_id: int,
    character_id: int,
    character_name: str,
    character_description: str,
) -> None:
    """Filter conversation for meaningful memories, then persist one row.

    Calls the significance-filter LLM to decide whether anything worth
    remembering happened. If yes, the distilled summary is embedded and
    inserted. If not, the save is skipped entirely.
    """
    lines = [f"{m.name}: {m.content}" for m in messages]
    if not lines:
        logger.warning("⚠️ No messages to evaluate for memory, skipping")
        return

    prompt = await memory_significance_prompt.ainvoke({
        "name": character_name,
        "description": character_description,
        "conversation": "\n".join(lines),
    })

    result = await memory_filter.ainvoke(prompt)
    extracted: str = result.content.strip()

    if not extracted or extracted.upper().startswith(NOTHING_MARKER):
        logger.info(f"🧹 {character_name}: nothing meaningful to remember, skipping save")
        return

    logger.info(f"🧠 {character_name}: meaningful memory extracted, saving")
    await save_memory(
        campaign_id, character_id,
        title=extracted.splitlines()[0][:120],
        content=extracted,
    )


def list_memories(campaign_id: int, character_id: int) -> list[dict[str, object]]:
    """📋 All memories of one character in a campaign, oldest first."""
    with _session() as s:
        rows = (
            s.query(CharacterMemory)
            .filter(
                CharacterMemory.campaign_id == campaign_id,
                CharacterMemory.character_id == character_id,
            )
            .order_by(CharacterMemory.created_at)
            .all()
        )
        return [_memory_dict(m) for m in rows]


def _memory_filters(memory_id: int, campaign_id: int | None) -> list:
    filters = [CharacterMemory.id == memory_id]
    if campaign_id is not None:
        filters.append(CharacterMemory.campaign_id == campaign_id)
    return filters


def get_memory(memory_id: int, campaign_id: int | None = None) -> dict[str, object] | None:
    """🧠 Fetch one memory; pass ``campaign_id`` to also require campaign ownership."""
    with _session() as s:
        memory = s.query(CharacterMemory).filter(*_memory_filters(memory_id, campaign_id)).first()
        return _memory_dict(memory) if memory else None


async def update_memory(
    memory_id: int,
    title: str | None = None,
    content: str | None = None,
    campaign_id: int | None = None,
) -> dict[str, object] | None:
    """✏️ Update a memory in place; re-embeds when the content changes.
    Pass ``campaign_id`` to also require campaign ownership."""
    vector = await _embed_or_none(content) if content is not None else None

    def _update() -> dict[str, object] | None:
        with _session() as s:
            memory = s.query(CharacterMemory).filter(*_memory_filters(memory_id, campaign_id)).first()
            if memory is None:
                return None
            if title is not None:
                memory.title = title.strip()
            if content is not None:
                memory.content = content.strip()
                memory.embedding = vector
            s.flush()
            return _memory_dict(memory)

    result = await asyncio.to_thread(_update)
    if result is not None:
        logger.info(f"✏️ Updated memory '{result['title']}' (id={memory_id})")
    return result


def delete_memory(memory_id: int, campaign_id: int | None = None) -> bool:
    """🗑️ Delete a single memory. Returns True if it existed.
    Pass ``campaign_id`` to also require campaign ownership."""
    with _session() as s:
        memory = s.query(CharacterMemory).filter(*_memory_filters(memory_id, campaign_id)).first()
        if memory is None:
            return False
        s.delete(memory)
        logger.info(f"🗑️ Deleted memory '{memory.title}' (id={memory_id})")
        return True


def wipe_character_memories(campaign_id: int, character_id: int) -> int:
    """🗑️ Delete all memories of one character within a campaign."""
    with _session() as s:
        deleted = (
            s.query(CharacterMemory)
            .filter(
                CharacterMemory.campaign_id == campaign_id,
                CharacterMemory.character_id == character_id,
            )
            .delete(synchronize_session=False)
        )
    logger.info(
        f"🗑️ Deleted {deleted} memories for character {character_id} (campaign {campaign_id})"
    )
    return deleted


def wipe_campaign_memories(campaign_id: int) -> int:
    """🗑️ Delete every campaign-scoped knowledge row: character memories,
    world events, DM secrets, and player preferences."""
    total = 0
    with _session() as s:
        for model in (CharacterMemory, *STREAM_MODELS):
            total += (
                s.query(model)
                .filter(model.campaign_id == campaign_id)
                .delete(synchronize_session=False)
            )
    logger.info(f"🗑️ Deleted {total} knowledge rows for campaign {campaign_id}")
    return total


# ---------------------------------------------------------------------------
# Campaign knowledge streams (generic over WorldEvent / DMSecret / PlayerPreference)
# ---------------------------------------------------------------------------


async def save_stream_items(model: type, campaign_id: int, items: list[str]) -> None:
    """🌍🤫🎯 Append rows to a campaign knowledge stream (one row per item)."""
    items = [i for i in items if i and i.strip()]
    if not items:
        return

    def _insert() -> None:
        with _session() as s:
            for item in items:
                s.add(model(campaign_id=campaign_id, content=item.strip()))

    await asyncio.to_thread(_insert)
    logger.info(f"💾 Saved {len(items)} {model.__name__} row(s) for campaign {campaign_id}")


def load_recent_stream(model: type, campaign_id: int, limit: int | None = None) -> str:
    """Load the most recent stream rows, newline-joined oldest-first."""
    limit = limit or _STREAM_LIMITS[model]
    with _session() as s:
        rows = (
            s.query(model)
            .filter(model.campaign_id == campaign_id)
            .order_by(model.id.desc())
            .limit(limit)
            .all()
        )
        return "\n".join(r.content for r in reversed(rows))
