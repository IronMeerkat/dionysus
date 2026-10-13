import logging

from fastapi import APIRouter, Body
from fastapi.exceptions import HTTPException

from contracts.turn_events import strip_speaker_prefix
from database.models import Campaign, Character, Conversation
from database.postgres_connection import db_session

logger = logging.getLogger(__name__)

session_router = APIRouter(prefix='/session')

_ROLE_MAP = {"human": "user", "ai": "assistant"}


def _conversation_response(conversation: Conversation) -> dict[str, object]:
    return {
        "id": conversation.id,
        "title": conversation.title or f"Conversation #{conversation.id}",
        "player": {"id": conversation.player.id, "name": conversation.player.name},
        "characters": [{"id": c.id, "name": c.name} for c in conversation.characters],
        "messages": [
            {
                "id": str(msg.id),
                "content": strip_speaker_prefix(msg.content, msg.speaker_name),
                "role": _ROLE_MAP.get(msg.role, msg.role),
                "name": msg.speaker_name or "",
                "created_at": msg.created_at.isoformat(),
            }
            for msg in conversation.messages
            if msg.role in _ROLE_MAP
        ],
    }


@session_router.post("/setup")
def setup_session(
    player_id: int = Body(...),
    character_ids: list[int] = Body(...),
    campaign_id: int = Body(...),
) -> dict[str, object]:
    """Create a new Conversation in the DB and return it.

    The client should then pass the returned ``id`` to the SocketIO
    ``init_session`` event to start the in-RAM session.
    """
    with db_session() as s:
        campaign = s.query(Campaign).filter(Campaign.id == campaign_id).first()
        if not campaign:
            raise HTTPException(status_code=404, detail="Campaign not found")
        # The player is whichever character the conversation designates as the PC.
        player = s.query(Character).filter(Character.id == player_id).first()
        if not player:
            raise HTTPException(status_code=404, detail="Player character not found")
        characters = s.query(Character).filter(Character.id.in_(character_ids)).all()
        if not characters:
            raise HTTPException(status_code=404, detail="Characters not found")

    conversation = Conversation.create(
        player=player,
        characters=characters,
        campaign_id=campaign_id,
    )
    logger.info(f"🎮 Created conversation {conversation.id} for player={player.name}")
    return _conversation_response(conversation)


@session_router.get("/options")
def get_options() -> dict:
    with db_session() as s:
        characters = s.query(Character.id, Character.name).order_by(Character.id.asc()).all()
    return {
        "characters": [{"id": c.id, "name": c.name} for c in characters],
    }


@session_router.get("/from_conversation/{conversation_id}")
def from_conversation(conversation_id: int) -> dict[str, object]:
    """Return full conversation data so the client can call ``init_session``."""
    with db_session() as s:
        conversation = s.query(Conversation).filter(Conversation.id == conversation_id).first()
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
        response = _conversation_response(conversation)
    logger.info(f"🔄 Loaded conversation {conversation_id}")
    return response
