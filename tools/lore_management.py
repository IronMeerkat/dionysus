import asyncio
from logging import getLogger

from langchain.tools import tool
from pydantic import BaseModel, Field

from database import knowledge

logger = getLogger(__name__)


class LoreEntryInput(BaseModel):
    title: str = Field(description="Specific, standalone title for this entry")
    content: str = Field(description="The full lore document, as markdown")


@tool
async def list_lore_entries(world_name: str) -> str:
    """List all lore entries in a world.

    Returns each entry's id, title, last-updated time, and a short content
    preview, one per line. Use read_lore_entry with an id to fetch the full
    markdown document.
    """
    world_id = await asyncio.to_thread(knowledge.get_world_id, world_name)
    if world_id is None:
        return f"❌ World '{world_name}' not found."

    entries = await asyncio.to_thread(knowledge.list_entries, world_id)
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
    entry = await asyncio.to_thread(knowledge.get_entry, entry_id)
    if entry is None:
        return f"❌ No lore entry found with id={entry_id}."
    logger.info(f"📖 Read lore entry '{entry['title']}' (id={entry_id})")
    return f"# {entry['title']}\n\n{entry['content']}"


@tool
async def save_lore_entries(entries: list[LoreEntryInput], world_name: str) -> str:
    """Save one or more lore documents to a world.

    Each entry should have a specific standalone title and full markdown
    content. To save a single document, pass a list with one entry.
    """
    world_id = await asyncio.to_thread(knowledge.get_world_id, world_name)
    if world_id is None:
        return f"❌ World '{world_name}' not found."

    valid = [e for e in entries if e.content.strip()]
    if not valid:
        return "❌ No entries to save: all content was empty."

    saved: list[str] = []
    failed: list[str] = []
    for entry in valid:
        try:
            await asyncio.to_thread(
                knowledge.create_entry, world_id, entry.title, entry.content.strip(),
            )
            saved.append(entry.title)
        except Exception:
            logger.exception(f"❌ Save failed for '{entry.title}'")
            failed.append(entry.title)

    logger.info(
        f"📦 Save complete for world '{world_name}': "
        f"{len(saved)} succeeded, {len(failed)} failed out of {len(valid)}"
    )
    result = f"✅ Saved {len(saved)} lore entries to world '{world_name}': "
    result += ", ".join(f"'{t}'" for t in saved) + "."
    if failed:
        result += f" ❌ Failed for: {', '.join(repr(t) for t in failed)}."
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

        world_id = await asyncio.to_thread(knowledge.get_world_id, world_name)
        if world_id is None:
            return f"❌ World '{world_name}' not found."

        updated = await asyncio.to_thread(
            knowledge.update_entry, entry_id, title=title, content=content, world_id=world_id,
        )
        if updated is None:
            return f"❌ No lore entry with id={entry_id} in world '{world_name}'."
        return f"✅ Updated '{updated['title']}' (id={entry_id}) in world '{world_name}'."
    except Exception as e:
        logger.exception(f"❌ Failed to update lore entry {entry_id}")
        return f"❌ Failed to update lore entry: {e}"


@tool
async def delete_lore_entry(entry_id: int, world_name: str) -> str:
    """Delete a lore entry by id. Verifies the entry belongs to the named world."""
    try:
        world_id = await asyncio.to_thread(knowledge.get_world_id, world_name)
        if world_id is None:
            return f"❌ World '{world_name}' not found."

        deleted = await asyncio.to_thread(knowledge.delete_entry, entry_id, world_id)
        if not deleted:
            return f"❌ No lore entry with id={entry_id} in world '{world_name}'."
        return f"✅ Deleted lore entry id={entry_id} from world '{world_name}'."
    except Exception as e:
        logger.exception(f"❌ Failed to delete lore entry {entry_id}")
        return f"❌ Failed to delete lore entry: {e}"
