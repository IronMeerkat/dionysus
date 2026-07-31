import logging

from fastapi import APIRouter, Body
from fastapi.exceptions import HTTPException

from database.models import Character, CharacterMemory
from database.postgres_connection import db_session

logger = logging.getLogger(__name__)

character_memories_router = APIRouter(prefix="/character-memories")


# ---------------------------------------------------------------------------
# Entry endpoints
# ---------------------------------------------------------------------------


@character_memories_router.get("/campaigns/{campaign_id}/npcs/{npc_id}/entries")
def api_list_entries(campaign_id: int, npc_id: int) -> list[dict[str, object]]:
    return [m.simple_dict for m in CharacterMemory.filter_by_campaign(campaign_id, npc_id)]


@character_memories_router.post("/campaigns/{campaign_id}/npcs/{npc_id}/entries", status_code=201)
async def api_create_entry(
    campaign_id: int,
    npc_id: int,
    title: str = Body(..., embed=True),
    content: str = Body(..., embed=True),
) -> dict[str, object]:
    with db_session() as s:
        npc = s.query(Character).filter(Character.id == npc_id).first()
        if not npc:
            raise HTTPException(status_code=404, detail=f"NPC {npc_id} not found")
        memory = CharacterMemory(campaign_id=campaign_id, character_id=npc.id, title=title.strip(), content=content.strip())
        s.add(memory)
        s.flush()
        response = memory.simple_dict
    logger.info(f"🧠 Created memory '{title}' for NPC '{npc.name}' in campaign {campaign_id}")
    return response


@character_memories_router.get("/entries/{memory_id}")
def api_get_entry(memory_id: int) -> dict[str, object]:
    with db_session() as s:
        memory = s.query(CharacterMemory).filter(CharacterMemory.id == memory_id).first()
        if memory is None:
            raise HTTPException(status_code=404, detail=f"Entry {memory_id} not found")
        return memory.simple_dict


@character_memories_router.put("/entries/{memory_id}")
async def api_update_entry(
    memory_id: int,
    title: str = Body(None, embed=True),
    content: str = Body(None, embed=True),
) -> dict[str, object]:
    with db_session() as s:
        memory = s.query(CharacterMemory).filter(CharacterMemory.id == memory_id).first()
        if memory is None:
            raise HTTPException(status_code=404, detail=f"Entry {memory_id} not found")
        if title is not None:
            memory.title = title.strip()
        if content is not None:
            memory.content = content.strip()
        s.flush()
        response = memory.simple_dict
    logger.info(f"✏️ Updated memory entry {memory_id}")
    return response


@character_memories_router.delete("/entries/{memory_id}")
def api_delete_entry(memory_id: int) -> dict[str, str]:
    with db_session() as s:
        memory = s.query(CharacterMemory).filter(CharacterMemory.id == memory_id).first()
        if memory is None:
            raise HTTPException(status_code=404, detail=f"Entry {memory_id} not found")
        s.delete(memory)
    logger.info(f"🗑️ Deleted memory entry {memory_id}")
    return {"detail": f"Entry {memory_id} deleted"}
