import logging

from fastapi import APIRouter, Body
from fastapi.exceptions import HTTPException
from tools.game_tabletop import tabletop

from database.models import Character, Player
from database.postgres_connection import session

from agents.dungeon_master import dungeon_master

logger = logging.getLogger(__name__)

session_router = APIRouter(prefix='/session')


@session_router.post("/setup")
def setup_session(player_id: int = Body(...), character_ids: list[int] = Body(...), start_new_conversation: bool = Body(...)) -> dict[str, str]:
    player = session.query(Player).filter(Player.id == player_id).first()
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")
    characters = session.query(Character).filter(Character.id.in_(character_ids)).all()
    if not characters:
        raise HTTPException(status_code=404, detail="Characters not found")
    tabletop.player = player
    tabletop.characters = characters
    if start_new_conversation:
        tabletop.messages = []
    tabletop.conversation = None
    dungeon_master.reload()
    return {"message": "Session setup complete"}

@session_router.get("/options")
def get_options() -> dict:
    players = session.query(Player.id, Player.name).order_by(Player.id.asc()).all()
    characters = session.query(Character.id, Character.name).order_by(Character.id.asc()).all()
    return {"players": [{"id": p.id, "name": p.name} for p in players], "characters": [{"id": c.id, "name": c.name} for c in characters]}

@session_router.put("/set_player", status_code=200)
def set_player(player_id: int = Body(..., embed=True)) -> dict[str, str]:
    player = session.query(Player).filter(Player.id == player_id).first()
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")
    tabletop.player = player
    dungeon_master.reload()
    return {"message": "Player set"}

@session_router.put("/set_characters", status_code=200)
def set_characters(character_ids: list[int] = Body(..., embed=True)) -> dict[str, str]:
    characters = session.query(Character).filter(Character.id.in_(character_ids)).all()
    if not characters:
        raise HTTPException(status_code=404, detail="Characters not found")
    tabletop.characters = characters
    dungeon_master.reload()
    return {"message": "Characters set"}    