import logging

from fastapi import APIRouter, Body
from fastapi.exceptions import HTTPException

from database.neo4j_lore import (
    create_entry,
    create_world_seed,
    delete_entry,
    delete_world,
    get_entry,
    list_lore_worlds,
    list_world_entries,
    update_entry,
    world_exists,
)

logger = logging.getLogger(__name__)

lore_router = APIRouter(prefix="/lore")


# ---------------------------------------------------------------------------
# World endpoints
# ---------------------------------------------------------------------------


@lore_router.get("/worlds")
async def api_list_worlds() -> list[dict[str, object]]:
    return await list_lore_worlds()


@lore_router.post("/worlds", status_code=201)
async def api_create_world(
    name: str = Body(..., embed=True),
) -> dict[str, object]:
    if await world_exists(name):
        raise HTTPException(status_code=409, detail=f"World '{name}' already exists")
    result = await create_world_seed(name)
    logger.info(f"🌍 Created world '{name}'")
    return result


@lore_router.delete("/worlds/{world_name}")
async def api_delete_world(world_name: str) -> dict[str, str]:
    if not await world_exists(world_name):
        raise HTTPException(status_code=404, detail=f"World '{world_name}' not found")
    count = await delete_world(world_name)
    logger.info(f"🗑️ Deleted world '{world_name}' ({count} episodes)")
    return {"detail": f"World '{world_name}' deleted ({count} episodes removed)"}


# ---------------------------------------------------------------------------
# Entry (episode) endpoints
# ---------------------------------------------------------------------------


@lore_router.get("/worlds/{world_name}/entries")
async def api_list_entries(world_name: str) -> list[dict[str, object]]:
    return await list_world_entries(world_name)


@lore_router.get("/entries/{episode_uuid}")
async def api_get_entry(episode_uuid: str) -> dict[str, object]:
    entry = await get_entry(episode_uuid)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Entry {episode_uuid} not found")
    return entry


@lore_router.post("/worlds/{world_name}/entries", status_code=201)
async def api_create_entry(
    world_name: str,
    title: str = Body(..., embed=True),
    content: str = Body(..., embed=True),
) -> dict[str, object]:
    return await create_entry(world_name, title, content)


@lore_router.put("/entries/{episode_uuid}")
async def api_update_entry(
    episode_uuid: str,
    title: str = Body(None, embed=True),
    content: str = Body(None, embed=True),
) -> dict[str, object]:
    result = await update_entry(episode_uuid, title=title, content=content)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Entry {episode_uuid} not found")
    logger.info(f"✏️ Updated entry {episode_uuid} -> {result['uuid']}")
    return result


@lore_router.delete("/entries/{episode_uuid}")
async def api_delete_entry(episode_uuid: str) -> dict[str, str]:
    deleted = await delete_entry(episode_uuid)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Entry {episode_uuid} not found")
    return {"detail": f"Entry {episode_uuid} deleted"}
