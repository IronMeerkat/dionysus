import logging
from uuid import UUID

from fastapi import APIRouter, Body, Path, Query
from fastapi.exceptions import HTTPException

from database.models import Character, Player, Message
from database.models.conversation import Conversation
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


def _get_conversation(conversation_id: int) -> Conversation:
    conversation = session.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conversation:
        raise HTTPException(status_code=404, detail=f"Conversation {conversation_id} not found")
    return conversation


@router.get('/conversations/{conversation_id}/story_background')
def get_story_background(conversation_id: int) -> dict[str, str]:
    conversation = _get_conversation(conversation_id)
    return {"story_background": conversation.story_background or ""}


@router.put("/conversations/{conversation_id}/story_background", status_code=200)
def update_story_background(conversation_id: int, story_background: str = Body(..., embed=True)) -> dict[str, str]:
    conversation = _get_conversation(conversation_id)
    conversation.story_background = story_background
    session.commit()
    logger.info(f"📜 Story background saved to conversation {conversation.id}")
    return {"message": "Story background updated"}


@router.get('/conversations/{conversation_id}/location')
def get_location(conversation_id: int) -> dict[str, str]:
    conversation = _get_conversation(conversation_id)
    return {"location": conversation.location or ""}


@router.put("/conversations/{conversation_id}/location", status_code=200)
def update_location(conversation_id: int, location: str = Body(..., embed=True)) -> dict[str, str]:
    conversation = _get_conversation(conversation_id)
    conversation.location = location
    session.commit()
    logger.info(f"📍 Location saved to conversation {conversation.id}")
    return {"message": "Location updated"}


@router.put('/messages/{message_id}', status_code=200)
def edit_message(message_id: UUID = Path(...), content: str = Body(..., embed=True)) -> dict[str, str]:
    message = session.query(Message).filter(Message.id == message_id).first()
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")
    message.content = content
    session.commit()
    logger.info(f"📝 Message {message_id} edited")
    return {"message": "Message edited"}


@router.delete('/messages/{message_id}', status_code=200)
def delete_message(message_id: UUID = Path(...)) -> dict[str, str]:
    message = session.query(Message).filter(Message.id == message_id).first()
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")
    session.delete(message)
    session.commit()
    logger.info(f"📝 Message {message_id} deleted")
    return {"message": "Message deleted"}
