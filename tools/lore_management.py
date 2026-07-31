"""📜 Lore library tools.

Talks to the database directly (no ``knowledge`` service indirection) so that
bulk saves collapse to a single SQLAlchemy Core ``insert ... returning``
round-trip via the 2.0 "insertmanyvalues" optimization, instead of N
serialized ORM commits.
"""
import asyncio
from datetime import datetime, timezone
from logging import getLogger

from langchain.tools import tool
from pydantic import BaseModel, Field
from sqlalchemy import delete, insert, select
from sqlalchemy.exc import SQLAlchemyError

from database.models import LoreEntry, World
from database.postgres_connection import db_session
from database.session_utils import embedder
from hephaestus.settings import settings

logger = getLogger(__name__)

# Preview length for list_lore_entries, kept in sync with the recall config
# that the knowledge service used to source.
_PREVIEW_CHARS = settings.memory.recall.lore_preview_chars


async def _embed_entries(texts: list[str]) -> list[list[float] | None]:
    """🧬 Embed lore payloads best-effort: a failed embed never blocks the
    write -- the row saves with a NULL vector and the backfill script
    (``scripts/vectorize_lore_entries.py``) picks it up later."""
    try:
        return await embedder.aembed_documents(texts)
    except Exception:
        logger.exception(f"💥 Lore embedding failed for {len(texts)} entr(ies); saving unvectorized")
        return [None] * len(texts)


class LoreEntryInput(BaseModel):
    title: str = Field(description="Specific, standalone title for this entry")
    content: str = Field(description="The full lore document, as markdown")


def _entry_row_dict(row) -> dict[str, object]:
    return {
        "id": row.id,
        "title": row.title,
        "content": row.content,
        "world_name": row.world_name,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


@tool
async def list_lore_entries(world_name: str) -> str:
    """List all lore entries in a world.

    Returns each entry's id, title, last-updated time, and a short content
    preview, one per line. Use read_lore_entry with an id to fetch the full
    markdown document.
    """

    def _list() -> tuple[int | None, list[dict[str, object]]]:
        with db_session() as s:
            world = s.query(World).filter(World.name == world_name.strip()).first()
            if world is None:
                return None, []
            rows = s.execute(
                select(
                    LoreEntry.id,
                    LoreEntry.title,
                    LoreEntry.content,
                    LoreEntry.created_at,
                    LoreEntry.updated_at,
                )
                .where(LoreEntry.world_id == world.id)
                .order_by(LoreEntry.created_at)
            ).all()
            entries = [
                {
                    "id": r.id,
                    "title": r.title,
                    "preview": " ".join(r.content.split())[:_PREVIEW_CHARS],
                    "created_at": r.created_at.isoformat(),
                    "updated_at": r.updated_at.isoformat(),
                }
                for r in rows
            ]
            return world.id, entries

    try:
        world, entries = await asyncio.to_thread(_list)
    except SQLAlchemyError:
        logger.error(f"❌ Failed to list lore entries for world '{world_name}'")
        return f"❌ Could not list lore entries for world '{world_name}' (database error)."
    if world is None:
        return f"❌ World '{world_name}' not found."
    if not entries:
        return f"🔍 No lore entries found in world '{world_name}'."

    lines = [
        f"- id={e['id']} | title='{e['title']}' | updated_at={e['updated_at']} "
        f"| preview='{e['preview']}'"
        for e in entries
    ]
    logger.info(f"📋 Listed {len(entries)} lore entries in world '{world_name}'")
    return "\n".join(lines)


@tool
async def read_lore_entry(entry_id: int) -> str:
    """Read the full markdown content of a single lore entry by its id.

    Use list_lore_entries first to discover the ids of relevant entries.
    """

    def _read() -> dict[str, object] | None:
        with db_session() as s:
            row = s.execute(
                select(
                    LoreEntry.id,
                    LoreEntry.title,
                    LoreEntry.content,
                    LoreEntry.created_at,
                    LoreEntry.updated_at,
                    World.name.label("world_name"),
                )
                .join(World, LoreEntry.world_id == World.id)
                .where(LoreEntry.id == entry_id)
            ).first()
            return _entry_row_dict(row) if row is not None else None

    try:
        entry = await asyncio.to_thread(_read)
    except SQLAlchemyError:
        logger.error(f"❌ Failed to read lore entry {entry_id}")
        return f"❌ Could not read lore entry id={entry_id} (database error)."
    if entry is None:
        return f"❌ No lore entry found with id={entry_id}."
    logger.info(f"📖 Read lore entry '{entry['title']}' (id={entry_id})")
    return f"# {entry['title']}\n\n{entry['content']}"


@tool
async def save_lore_entries(entries: list[LoreEntryInput], world_name: str) -> str:
    """Save one or more lore documents to a world.

    Each entry should have a specific standalone title and full markdown
    content. To save a single document, pass a list with one entry. All
    entries are inserted in a single transaction with one round-trip.
    """
    valid = [e for e in entries if e.content.strip()]
    if not valid:
        return "❌ No entries to save: all content was empty."

    vectors = await _embed_entries(
        [LoreEntry.embedding_text(e.title, e.content) for e in valid]
    )

    def _bulk_save() -> tuple[int | None, list[dict[str, object]]]:
        # Single timestamp for the whole batch -- avoids N Python-side
        # default evaluations and keeps created/updated consistent.
        now = datetime.now(timezone.utc)
        with db_session() as s:
            world = s.query(World).filter(World.name == world_name.strip()).first()
            if world is None:
                return None, []
            rows = [
                {
                    "world_id": world.id,
                    "title": e.title.strip(),
                    "content": e.content.strip(),
                    "embedding": vector,
                    "created_at": now,
                    "updated_at": now,
                }
                for e, vector in zip(valid, vectors)
            ]
            # Core insert with returning: SQLAlchemy 2.0 batches this into one
            # executemany + RETURNING round-trip (insertmanyvalues), returning
            # the generated ids and timestamps for every row.
            stmt = (
                insert(LoreEntry)
                .values(rows)
                .returning(
                    LoreEntry.id,
                    LoreEntry.title,
                    LoreEntry.created_at,
                    LoreEntry.updated_at,
                )
            )
            result = s.execute(stmt)
            saved = [
                {
                    "id": r.id,
                    "title": r.title,
                    "created_at": r.created_at.isoformat(),
                    "updated_at": r.updated_at.isoformat(),
                }
                for r in result
            ]
            return world.id, saved

    try:
        world, saved = await asyncio.to_thread(_bulk_save)
    except Exception:
        logger.exception(f"❌ Bulk save failed for world '{world_name}'")
        titles = ", ".join(f"'{e.title}'" for e in valid)
        return f"❌ Failed to save {len(valid)} lore entries to world '{world_name}' ({titles})."

    if world is None:
        return f"❌ World '{world_name}' not found."

    titles = [r["title"] for r in saved]
    logger.info(f"📦 Bulk-saved {len(titles)} lore entries to world '{world_name}'")
    result = f"✅ Saved {len(titles)} lore entries to world '{world_name}': "
    result += ", ".join(f"'{t}'" for t in titles) + "."
    return result


@tool
async def update_lore_entry(
    entry_id: int,
    world_name: str,
    title: str | None = None,
    content: str | None = None,
) -> str:
    """Modify an existing lore entry's title and/or content.

    Provide only the field(s) you want to change; the other is preserved.
    The entry keeps its id. Verifies the entry belongs to the named world.
    """
    try:
        if title is None and content is None:
            return "❌ Nothing to update: provide a new title and/or content."
        if content is not None:
            content = content.strip()
            if not content:
                return "❌ Failed to update lore entry: content is empty."

        def _current() -> tuple[str, str] | None:
            """Existing (title, content) so the re-embed covers the merged result."""
            with db_session() as s:
                row = s.execute(
                    select(LoreEntry.title, LoreEntry.content).where(LoreEntry.id == entry_id)
                ).first()
                return (row.title, row.content) if row is not None else None

        current = await asyncio.to_thread(_current)
        if current is None:
            return f"❌ No lore entry with id={entry_id}."
        new_title = title.strip() if title is not None else current[0]
        new_content = content if content is not None else current[1]
        (vector,) = await _embed_entries([LoreEntry.embedding_text(new_title, new_content)])

        def _update() -> str:
            with db_session() as s:
                world = s.query(World).filter(World.name == world_name.strip()).first()
                if world is None:
                    return f"❌ World '{world_name}' not found."
                entry = s.execute(
                    select(LoreEntry).where(
                        LoreEntry.id == entry_id,
                        LoreEntry.world_id == world.id,
                    )
                ).scalar_one_or_none()
                if entry is None:
                    return f"❌ No lore entry with id={entry_id} in world '{world_name}'."
                if title is not None:
                    entry.title = title.strip()
                if content is not None:
                    entry.content = content
                entry.embedding = vector
                s.flush()
                logger.info(f"✏️ Updated lore entry '{entry.title}' (id={entry_id})")
                return f"✅ Updated '{entry.title}' (id={entry_id}) in world '{world_name}'."

        return await asyncio.to_thread(_update)
    except Exception as e:
        logger.exception(f"❌ Failed to update lore entry {entry_id}")
        return f"❌ Failed to update lore entry: {e}"


@tool
async def delete_lore_entry(entry_id: int, world_name: str) -> str:
    """Delete a lore entry by id. Verifies the entry belongs to the named world."""
    try:
        def _delete() -> str:
            with db_session() as s:
                world = s.query(World).filter(World.name == world_name.strip()).first()
                if world is None:
                    return f"❌ World '{world_name}' not found."
                # Single DELETE ... RETURNING would also work, but we need the
                # world-ownership check first; a targeted delete is one round-trip.
                deleted = s.execute(
                    delete(LoreEntry)
                    .where(
                        LoreEntry.id == entry_id,
                        LoreEntry.world_id == world.id,
                    )
                ).rowcount
                if not deleted:
                    return f"❌ No lore entry with id={entry_id} in world '{world_name}'."
                logger.info(f"🗑️ Deleted lore entry id={entry_id} from world '{world_name}'")
                return f"✅ Deleted lore entry id={entry_id} from world '{world_name}'."

        return await asyncio.to_thread(_delete)
    except Exception as e:
        logger.exception(f"❌ Failed to delete lore entry {entry_id}")
        return f"❌ Failed to delete lore entry: {e}"
