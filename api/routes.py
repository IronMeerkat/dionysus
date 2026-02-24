import logging

from fastapi import APIRouter

from tools.game_tabletop import tabletop

from database.models import Character, Player
from database.postgres_connection import session

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/players")
def get_players() -> list[dict[str, object]]:
    players = session.query(Player.id, Player.name).order_by(Player.id.asc()).all()
    return [{"id": p.id, "name": p.name} for p in players]


@router.get("/characters")
def get_characters() -> list[dict[str, object]]:
    characters = session.query(Character.id, Character.name).order_by(Character.id.asc()).all()
    return [{"id": c.id, "name": c.name} for c in characters]


@router.get('/story_background')
def get_story_background() -> dict[str, str]:
    return {"story_background": tabletop.story_background}

@router.put("/story_background", status_code=200)
def update_story_background(payload: dict[str, str]) -> dict[str, str]:
    tabletop.story_background = payload["story_background"]
    return {"message": "Story background updated"}

@router.get('/location')
def get_location() -> dict[str, str]:
    return {"location": tabletop.location}

@router.put("/location", status_code=200)
def update_location(payload: dict[str, str]) -> dict[str, str]:
    tabletop.location = payload["location"]
    return {"message": "Location updated"}