import logging

from fastapi import APIRouter, Body
from fastapi.exceptions import HTTPException

from database.models.lore import LoreEntry, World
from database.postgres_connection import db_session

logger = logging.getLogger(__name__)

lore_router = APIRouter(prefix="/lore")


# ---------------------------------------------------------------------------
# World endpoints
# ---------------------------------------------------------------------------


@lore_router.get("/worlds")
def api_list_worlds() -> list[dict[str, object]]:
    """🌍 All worlds, alphabetically, with entry counts."""
    with db_session() as s:
        worlds = s.query(World).order_by(World.name).all()
        return [world.simple_dict for world in worlds]


@lore_router.post("/worlds", status_code=201)
def api_create_world(
    name: str = Body(..., embed=True),
    description: str = Body("", embed=True),
) -> dict[str, object]:
    with db_session() as s:
        if s.query(World).filter(World.name == name.strip()).first() is not None:
            raise HTTPException(status_code=409, detail=f"World '{name}' already exists")
        world = World(name=name.strip(), description=description.strip())
        s.add(world)
        s.flush()
        response = world.simple_dict
    logger.info(f"🌍 Created world '{world.name}' (id={world.id})")
    return response


@lore_router.delete("/worlds/{world_name}")
def api_delete_world(world_name: str) -> dict[str, str]:
    with db_session() as s:
        world = s.query(World).filter(World.name == world_name.strip()).first()
        if world is None:
            raise HTTPException(status_code=404, detail=f"World '{world_name}' not found")
        count = s.query(LoreEntry).filter(LoreEntry.world_id == world.id).delete()
        world_id = world.id
        s.delete(world)
    logger.info(f"🗑️ Deleted world '{world_name}' (id={world_id}, {count} entries)")
    return {"detail": f"World '{world_name}' deleted ({count} entries removed)"}


# ---------------------------------------------------------------------------
# Entry endpoints
# ---------------------------------------------------------------------------


@lore_router.get("/worlds/{world_name}/entries")
def api_list_entries(world_name: str) -> list[dict[str, object]]:
    world = World.get_world_by_name(world_name.strip())
    if world is None:
        raise HTTPException(status_code=404, detail=f"World '{world_name}' not found")
    return LoreEntry.preview_entries(world)


@lore_router.get("/entries/{entry_id}")
def api_get_entry(entry_id: int) -> dict[str, object]:
    with db_session() as s:
        entry = s.query(LoreEntry).filter(LoreEntry.id == entry_id).first()
        if entry is None:
            raise HTTPException(status_code=404, detail=f"Entry {entry_id} not found")
        return entry.simple_dict


@lore_router.post("/worlds/{world_name}/entries", status_code=201)
def api_create_entry(
    world_name: str,
    title: str = Body(..., embed=True),
    content: str = Body(..., embed=True),
) -> dict[str, object]:
    with db_session() as s:
        world = s.query(World).filter(World.name == world_name.strip()).first()
        if world is None:
            raise HTTPException(status_code=404, detail=f"World '{world_name}' not found")
        entry = LoreEntry(world_id=world.id, title=title.strip(), content=content.strip())
        s.add(entry)
        s.flush()
        response = entry.simple_dict
    logger.info(f"📜 Created entry '{entry.title}' (id={entry.id}) in world '{world_name}'")
    return response


@lore_router.put("/entries/{entry_id}")
def api_update_entry(
    entry_id: int,
    title: str = Body(None, embed=True),
    content: str = Body(None, embed=True),
) -> dict[str, object]:
    with db_session() as s:
        entry = s.query(LoreEntry).filter(LoreEntry.id == entry_id).first()
        if entry is None:
            raise HTTPException(status_code=404, detail=f"Entry {entry_id} not found")
        if title is not None:
            entry.title = title.strip()
        if content is not None:
            entry.content = content.strip()
        s.flush()
        response = entry.simple_dict
    logger.info(f"📜 Updated entry '{entry.title}' (id={entry.id})")
    return response


@lore_router.delete("/entries/{entry_id}")
def api_delete_entry(entry_id: int) -> dict[str, str]:
    with db_session() as s:
        entry = s.query(LoreEntry).filter(LoreEntry.id == entry_id).first()
        if entry is None:
            raise HTTPException(status_code=404, detail=f"Entry {entry_id} not found")
        entry_title = entry.title
        s.delete(entry)
    logger.info(f"🗑️ Deleted entry '{entry_title}' (id={entry_id})")
    return {"detail": f"Entry {entry_id} deleted"}
