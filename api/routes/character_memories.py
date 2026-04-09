import logging

from fastapi import APIRouter, Body
from fastapi.exceptions import HTTPException

from database.models import Character
from database.postgres_connection import session
from database.graphiti_utils import make_memory_group_id
from database.graphiti_worlds import (
    create_entry,
    delete_entity,
    delete_entry,
    get_entity,
    get_entry,
    list_entities,
    list_entries,
    update_entity,
    update_entry,
)

logger = logging.getLogger(__name__)

character_memories_router = APIRouter(prefix="/character-memories")


def _resolve_npc(npc_id: int) -> Character:
    """Look up an NPC by ID, raising 404 if not found."""
    npc = session.query(Character).filter(Character.id == npc_id).first()
    if not npc:
        raise HTTPException(status_code=404, detail=f"NPC {npc_id} not found")
    return npc


def _memory_group(campaign_id: int, npc_name: str) -> str:
    return make_memory_group_id(campaign_id, npc_name)


def _entry_to_response(entry: dict[str, object]) -> dict[str, object]:
    """Strip ``group_id`` from the entry dict before sending to the client."""
    entry.pop("group_id", None)
    return entry


# ---------------------------------------------------------------------------
# Entry endpoints
# ---------------------------------------------------------------------------


@character_memories_router.get("/campaigns/{campaign_id}/npcs/{npc_id}/entries")
async def api_list_entries(campaign_id: int, npc_id: int) -> list[dict[str, object]]:
    npc = _resolve_npc(npc_id)
    gid = _memory_group(campaign_id, npc.name)
    episodes = await list_entries(gid)
    for ep in episodes:
        ep.setdefault("kind", "episode")
    entities = await list_entities(gid)
    return episodes + entities


@character_memories_router.post("/campaigns/{campaign_id}/npcs/{npc_id}/entries", status_code=201)
async def api_create_entry(
    campaign_id: int,
    npc_id: int,
    title: str = Body(..., embed=True),
    content: str = Body(..., embed=True),
) -> dict[str, object]:
    npc = _resolve_npc(npc_id)
    gid = _memory_group(campaign_id, npc.name)
    entry = await create_entry(gid, title, content, source_description=f"manual:{npc.name}")
    logger.info(f"🧠 Created memory '{title}' for NPC '{npc.name}' in campaign {campaign_id}")
    return _entry_to_response(entry)


@character_memories_router.get("/entries/{episode_uuid}")
async def api_get_entry(episode_uuid: str) -> dict[str, object]:
    entry = await get_entry(episode_uuid)
    if entry is None:
        entry = await get_entity(episode_uuid)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Entry {episode_uuid} not found")
    return _entry_to_response(entry)


@character_memories_router.put("/entries/{episode_uuid}")
async def api_update_entry(
    episode_uuid: str,
    title: str = Body(None, embed=True),
    content: str = Body(None, embed=True),
) -> dict[str, object]:
    result = await update_entry(episode_uuid, title=title, content=content)
    if result is None:
        result = await update_entity(episode_uuid, name=title, summary=content)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Entry {episode_uuid} not found")
    logger.info(f"✏️ Updated memory entry {episode_uuid} -> {result['uuid']}")
    return _entry_to_response(result)


@character_memories_router.delete("/entries/{episode_uuid}")
async def api_delete_entry(episode_uuid: str) -> dict[str, str]:
    deleted = await delete_entry(episode_uuid)
    if not deleted:
        deleted = await delete_entity(episode_uuid)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Entry {episode_uuid} not found")
    return {"detail": f"Entry {episode_uuid} deleted"}
