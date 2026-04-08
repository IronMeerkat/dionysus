import logging

from fastapi import APIRouter, Body
from fastapi.exceptions import HTTPException

from database.models.character import Player
from database.postgres_connection import session

logger = logging.getLogger(__name__)

players_router = APIRouter(prefix="/players")


def _player_list_item(player: Player) -> dict[str, object]:
    return {
        "id": player.id,
        "name": player.name,
        "description": player.description,
        "description_version": player.description_version,
        "created_at": player.created_at.isoformat(),
    }


def _player_full(player: Player) -> dict[str, object]:
    return {
        "id": player.id,
        "name": player.name,
        "created_at": player.created_at.isoformat(),
        "descriptions": [
            {
                "version": desc.version,
                "body": desc.body,
                "created_at": desc.created_at.isoformat(),
            }
            for desc in player.description_versions
        ],
    }


def _get_player(player_id: int) -> Player:
    player = session.query(Player).filter(Player.id == player_id).first()
    if not player:
        raise HTTPException(status_code=404, detail=f"Player {player_id} not found")
    return player


@players_router.get("/")
def list_players() -> list[dict[str, object]]:
    players = session.query(Player).order_by(Player.name.asc()).all()
    return [_player_list_item(p) for p in players]


@players_router.get("/{player_id}")
def get_player(player_id: int) -> dict[str, object]:
    player = _get_player(player_id)
    return _player_full(player)


@players_router.post("/", status_code=201)
def create_player(
    name: str = Body(..., embed=True),
    description: str = Body("", embed=True),
) -> dict[str, object]:
    existing = session.query(Player).filter(Player.name == name).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Player '{name}' already exists")
    player = Player(name=name)
    if description.strip():
        player.add_description(description.strip())
    session.add(player)
    session.commit()
    logger.info(f"🎮 Created player '{name}' (id={player.id})")
    return _player_full(player)


@players_router.put("/{player_id}")
def update_player(
    player_id: int,
    name: str = Body(..., embed=True),
) -> dict[str, object]:
    player = _get_player(player_id)
    dup = session.query(Player).filter(Player.name == name, Player.id != player_id).first()
    if dup:
        raise HTTPException(status_code=409, detail=f"Player '{name}' already exists")
    player.name = name
    session.commit()
    logger.info(f"✏️ Updated player {player_id} name to '{name}'")
    return _player_full(player)


@players_router.post("/{player_id}/description", status_code=201)
def add_player_description(
    player_id: int,
    body: str = Body(..., embed=True),
) -> dict[str, object]:
    player = _get_player(player_id)
    player.add_description(body.strip())
    session.commit()
    logger.info(f"📝 Added description v{player.description_version} to player '{player.name}'")
    return _player_full(player)


@players_router.delete("/{player_id}")
def delete_player(player_id: int) -> dict[str, str]:
    player = _get_player(player_id)
    name = player.name
    session.delete(player)
    session.commit()
    logger.info(f"🗑️ Deleted player '{name}' (id={player_id})")
    return {"detail": f"Player '{name}' deleted"}
