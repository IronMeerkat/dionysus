import logging

from fastapi import APIRouter, Body
from fastapi.exceptions import HTTPException

from database.models.world import LoreEntry, World
from database.postgres_connection import session
from tools.lore_management import spawn_ingestion_task

logger = logging.getLogger(__name__)

lore_router = APIRouter(prefix="/lore")


def _world_response(world: World) -> dict[str, object]:
    return {
        "id": world.id,
        "name": world.name,
        "description": world.description or "",
        "entry_count": len(world.lore_entries),
    }


def _entry_list_item(entry: LoreEntry) -> dict[str, object]:
    return {
        "id": entry.id,
        "title": entry.title,
        "category": entry.category,
        "ingestion_status": entry.ingestion_status,
        "created_at": entry.created_at.isoformat(),
        "updated_at": entry.updated_at.isoformat(),
    }


def _entry_full(entry: LoreEntry) -> dict[str, object]:
    return {
        "id": entry.id,
        "title": entry.title,
        "content": entry.content,
        "category": entry.category,
        "ingestion_status": entry.ingestion_status,
        "world_id": entry.world_id,
        "created_at": entry.created_at.isoformat(),
        "updated_at": entry.updated_at.isoformat(),
    }


def _get_world(world_id: int) -> World:
    world = session.query(World).filter(World.id == world_id).first()
    if not world:
        raise HTTPException(status_code=404, detail=f"World {world_id} not found")
    return world


def _get_entry(entry_id: int) -> LoreEntry:
    entry = session.query(LoreEntry).filter(LoreEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail=f"Lore entry {entry_id} not found")
    return entry


# ---------------------------------------------------------------------------
# World endpoints
# ---------------------------------------------------------------------------


@lore_router.get("/worlds")
def list_worlds() -> list[dict[str, object]]:
    worlds = session.query(World).order_by(World.name.asc()).all()
    return [_world_response(w) for w in worlds]


@lore_router.post("/worlds", status_code=201)
def create_world(
    name: str = Body(..., embed=True),
    description: str = Body("", embed=True),
) -> dict[str, object]:
    existing = session.query(World).filter(World.name == name).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"World '{name}' already exists")
    world = World(name=name, description=description)
    session.add(world)
    session.commit()
    logger.info(f"🌍 Created world '{name}' (id={world.id})")
    return _world_response(world)


@lore_router.put("/worlds/{world_id}")
def update_world(
    world_id: int,
    name: str = Body(None, embed=True),
    description: str = Body(None, embed=True),
) -> dict[str, object]:
    world = _get_world(world_id)
    if name is not None:
        dup = session.query(World).filter(World.name == name, World.id != world_id).first()
        if dup:
            raise HTTPException(status_code=409, detail=f"World '{name}' already exists")
        world.name = name
    if description is not None:
        world.description = description
    session.commit()
    logger.info(f"✏️ Updated world {world_id}")
    return _world_response(world)


@lore_router.delete("/worlds/{world_id}")
def delete_world(world_id: int) -> dict[str, str]:
    world = _get_world(world_id)
    session.delete(world)
    session.commit()
    logger.info(f"🗑️ Deleted world '{world.name}' (id={world_id})")
    return {"detail": f"World '{world.name}' deleted"}


# ---------------------------------------------------------------------------
# LoreEntry endpoints
# ---------------------------------------------------------------------------


@lore_router.get("/worlds/{world_id}/entries")
def list_entries(world_id: int) -> list[dict[str, object]]:
    world = _get_world(world_id)
    return [_entry_list_item(e) for e in world.lore_entries]


@lore_router.get("/entries/{entry_id}")
def get_entry(entry_id: int) -> dict[str, object]:
    entry = _get_entry(entry_id)
    return _entry_full(entry)


@lore_router.post("/worlds/{world_id}/entries", status_code=201)
def create_entry(
    world_id: int,
    title: str = Body(..., embed=True),
    content: str = Body(..., embed=True),
    category: str = Body(None, embed=True),
) -> dict[str, object]:
    world = _get_world(world_id)
    entry = LoreEntry(world_id=world.id, title=title, content=content, category=category)
    session.add(entry)
    session.commit()
    logger.info(f"📜 Created lore entry '{title}' (id={entry.id}) in world '{world.name}'")
    return _entry_full(entry)


@lore_router.put("/entries/{entry_id}")
def update_entry(
    entry_id: int,
    title: str = Body(None, embed=True),
    content: str = Body(None, embed=True),
    category: str = Body(None, embed=True),
) -> dict[str, object]:
    entry = _get_entry(entry_id)
    if title is not None:
        entry.title = title
    if content is not None:
        entry.content = content
    if category is not None:
        entry.category = category
    session.commit()
    logger.info(f"✏️ Updated lore entry {entry_id}")
    return _entry_full(entry)


@lore_router.delete("/entries/{entry_id}")
def delete_entry(entry_id: int) -> dict[str, str]:
    entry = _get_entry(entry_id)
    title = entry.title
    session.delete(entry)
    session.commit()
    logger.info(f"🗑️ Deleted lore entry '{title}' (id={entry_id})")
    return {"detail": f"Lore entry '{title}' deleted"}


@lore_router.post("/entries/{entry_id}/reingest")
def reingest_entry(entry_id: int) -> dict[str, object]:
    """Re-trigger Graphiti ingestion for a failed entry."""
    entry = _get_entry(entry_id)
    if entry.ingestion_status != "failed":
        raise HTTPException(
            status_code=409,
            detail=f"Entry ingestion_status is '{entry.ingestion_status}', not 'failed'",
        )
    entry.ingestion_status = "pending"
    session.commit()

    spawn_ingestion_task(
        entry_id=entry.id,
        title=entry.title,
        content=entry.content,
        world_name=entry.world.name,
        group_id=entry.world.graphiti_group_id,
    )
    logger.info(f"🔄 Re-ingestion spawned for entry '{entry.title}' (id={entry_id})")
    return _entry_full(entry)
