import logging

from fastapi import APIRouter, Body
from fastapi.exceptions import HTTPException

from database.models.character import Character
from database.postgres_connection import session

logger = logging.getLogger(__name__)

npcs_router = APIRouter(prefix="/npcs")


def _npc_list_item(character: Character) -> dict[str, object]:
    return {
        "id": character.id,
        "name": character.name,
        "description": character.description,
        "description_version": character.description_version,
        "created_at": character.created_at.isoformat(),
    }


def _npc_full(character: Character) -> dict[str, object]:
    return {
        "id": character.id,
        "name": character.name,
        "created_at": character.created_at.isoformat(),
        "descriptions": [
            {
                "version": desc.version,
                "body": desc.body,
                "created_at": desc.created_at.isoformat(),
            }
            for desc in character.description_versions
        ],
    }


def _get_npc(npc_id: int) -> Character:
    character = session.query(Character).filter(Character.id == npc_id).first()
    if not character:
        raise HTTPException(status_code=404, detail=f"NPC {npc_id} not found")
    return character


@npcs_router.get("/")
def list_npcs() -> list[dict[str, object]]:
    characters = session.query(Character).order_by(Character.name.asc()).all()
    return [_npc_list_item(c) for c in characters]


@npcs_router.get("/{npc_id}")
def get_npc(npc_id: int) -> dict[str, object]:
    character = _get_npc(npc_id)
    return _npc_full(character)


@npcs_router.post("/", status_code=201)
def create_npc(
    name: str = Body(..., embed=True),
    description: str = Body("", embed=True),
) -> dict[str, object]:
    existing = session.query(Character).filter(Character.name == name).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"NPC '{name}' already exists")
    character = Character(name=name)
    if description.strip():
        character.add_description(description.strip())
    session.add(character)
    session.commit()
    logger.info(f"🎭 Created NPC '{name}' (id={character.id})")
    return _npc_full(character)


@npcs_router.put("/{npc_id}")
def update_npc(
    npc_id: int,
    name: str = Body(..., embed=True),
) -> dict[str, object]:
    character = _get_npc(npc_id)
    dup = session.query(Character).filter(Character.name == name, Character.id != npc_id).first()
    if dup:
        raise HTTPException(status_code=409, detail=f"NPC '{name}' already exists")
    character.name = name
    session.commit()
    logger.info(f"✏️ Updated NPC {npc_id} name to '{name}'")
    return _npc_full(character)


@npcs_router.post("/{npc_id}/description", status_code=201)
def add_npc_description(
    npc_id: int,
    body: str = Body(..., embed=True),
) -> dict[str, object]:
    character = _get_npc(npc_id)
    character.add_description(body.strip())
    session.commit()
    logger.info(f"📝 Added description v{character.description_version} to NPC '{character.name}'")
    return _npc_full(character)


@npcs_router.delete("/{npc_id}")
def delete_npc(npc_id: int) -> dict[str, str]:
    character = _get_npc(npc_id)
    name = character.name
    session.delete(character)
    session.commit()
    logger.info(f"🗑️ Deleted NPC '{name}' (id={npc_id})")
    return {"detail": f"NPC '{name}' deleted"}
