import logging

from fastapi import APIRouter, Body
from fastapi.exceptions import HTTPException

from database import knowledge
from database.models import Character
from database.postgres_connection import session

logger = logging.getLogger(__name__)

character_memories_router = APIRouter(prefix="/character-memories")


# ---------------------------------------------------------------------------
# Entry endpoints
# ---------------------------------------------------------------------------


@character_memories_router.get("/campaigns/{campaign_id}/npcs/{npc_id}/entries")
def api_list_entries(campaign_id: int, npc_id: int) -> list[dict[str, object]]:
    return knowledge.list_memories(campaign_id, npc_id)


@character_memories_router.post("/campaigns/{campaign_id}/npcs/{npc_id}/entries", status_code=201)
async def api_create_entry(
    campaign_id: int,
    npc_id: int,
    title: str = Body(..., embed=True),
    content: str = Body(..., embed=True),
) -> dict[str, object]:
    npc = session.query(Character).filter(Character.id == npc_id).first()
    if not npc:
        raise HTTPException(status_code=404, detail=f"NPC {npc_id} not found")
    memory = await knowledge.save_memory(campaign_id, npc.id, title, content)
    logger.info(f"🧠 Created memory '{title}' for NPC '{npc.name}' in campaign {campaign_id}")
    return memory


@character_memories_router.get("/entries/{memory_id}")
def api_get_entry(memory_id: int) -> dict[str, object]:
    memory = knowledge.get_memory(memory_id)
    if memory is None:
        raise HTTPException(status_code=404, detail=f"Entry {memory_id} not found")
    return memory


@character_memories_router.put("/entries/{memory_id}")
async def api_update_entry(
    memory_id: int,
    title: str = Body(None, embed=True),
    content: str = Body(None, embed=True),
) -> dict[str, object]:
    result = await knowledge.update_memory(memory_id, title=title, content=content)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Entry {memory_id} not found")
    logger.info(f"✏️ Updated memory entry {memory_id}")
    return result


@character_memories_router.delete("/entries/{memory_id}")
def api_delete_entry(memory_id: int) -> dict[str, str]:
    if not knowledge.delete_memory(memory_id):
        raise HTTPException(status_code=404, detail=f"Entry {memory_id} not found")
    return {"detail": f"Entry {memory_id} deleted"}
