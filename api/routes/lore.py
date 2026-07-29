import logging

from fastapi import APIRouter, Body
from fastapi.exceptions import HTTPException

from database import knowledge

logger = logging.getLogger(__name__)

lore_router = APIRouter(prefix="/lore")


def _resolve_world(world_name: str) -> dict[str, object]:
    world = knowledge.get_world_by_name(world_name)
    if world is None:
        raise HTTPException(status_code=404, detail=f"World '{world_name}' not found")
    return world


# ---------------------------------------------------------------------------
# World endpoints
# ---------------------------------------------------------------------------


@lore_router.get("/worlds")
def api_list_worlds() -> list[dict[str, object]]:
    return knowledge.list_worlds()


@lore_router.post("/worlds", status_code=201)
def api_create_world(
    name: str = Body(..., embed=True),
    description: str = Body("", embed=True),
) -> dict[str, object]:
    if knowledge.get_world_by_name(name.strip()) is not None:
        raise HTTPException(status_code=409, detail=f"World '{name}' already exists")
    return knowledge.create_world(name, description)


@lore_router.delete("/worlds/{world_name}")
def api_delete_world(world_name: str) -> dict[str, str]:
    world = _resolve_world(world_name)
    count = knowledge.delete_world(world["id"])
    return {"detail": f"World '{world_name}' deleted ({count} entries removed)"}


# ---------------------------------------------------------------------------
# Entry endpoints
# ---------------------------------------------------------------------------


@lore_router.get("/worlds/{world_name}/entries")
def api_list_entries(world_name: str) -> list[dict[str, object]]:
    world = _resolve_world(world_name)
    return knowledge.list_entries(world["id"])


@lore_router.get("/entries/{entry_id}")
def api_get_entry(entry_id: int) -> dict[str, object]:
    entry = knowledge.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Entry {entry_id} not found")
    return entry


@lore_router.post("/worlds/{world_name}/entries", status_code=201)
def api_create_entry(
    world_name: str,
    title: str = Body(..., embed=True),
    content: str = Body(..., embed=True),
) -> dict[str, object]:
    world = _resolve_world(world_name)
    entry = knowledge.create_entry(world["id"], title, content)
    logger.info(f"📜 Created entry '{entry['title']}' (id={entry['id']}) in world '{world_name}'")
    return entry


@lore_router.put("/entries/{entry_id}")
def api_update_entry(
    entry_id: int,
    title: str = Body(None, embed=True),
    content: str = Body(None, embed=True),
) -> dict[str, object]:
    result = knowledge.update_entry(entry_id, title=title, content=content)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Entry {entry_id} not found")
    return result


@lore_router.delete("/entries/{entry_id}")
def api_delete_entry(entry_id: int) -> dict[str, str]:
    if not knowledge.delete_entry(entry_id):
        raise HTTPException(status_code=404, detail=f"Entry {entry_id} not found")
    return {"detail": f"Entry {entry_id} deleted"}
