import logging
from uuid import UUID

from fastapi import APIRouter, Body, Path, Query
from fastapi.exceptions import HTTPException

from api.events import get_live_conversation
from database.models import Character, Message
from database.models.conversation import Conversation
from database.postgres_connection import db_session
from tools.world_state import get_world_state, set_location

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/characters")
def get_characters() -> list[dict[str, object]]:
    with db_session() as s:
        characters = s.query(Character.id, Character.name).order_by(Character.id.asc()).all()
    return [{"id": c.id, "name": c.name} for c in characters]


def _get_conversation(s, conversation_id: int) -> Conversation:
    conversation = s.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conversation:
        raise HTTPException(status_code=404, detail=f"Conversation {conversation_id} not found")
    return conversation


@router.get('/conversations/{conversation_id}/story_background')
def get_story_background(conversation_id: int) -> dict[str, str]:
    with db_session() as s:
        conversation = _get_conversation(s, conversation_id)
        return {"story_background": conversation.campaign.story_background or ""}


@router.put("/conversations/{conversation_id}/story_background", status_code=200)
def update_story_background(conversation_id: int, story_background: str = Body(..., embed=True)) -> dict[str, str]:
    with db_session() as s:
        conversation = _get_conversation(s, conversation_id)
        campaign = conversation.campaign
        campaign.story_background = story_background
        campaign_id = campaign.id
    logger.info(f"📜 Story background saved to campaign {campaign_id}")
    return {"message": "Story background updated"}


@router.get('/conversations/{conversation_id}/location')
def get_location(conversation_id: int) -> dict[str, str]:
    with db_session() as s:
        conversation = _get_conversation(s, conversation_id)
        campaign_id = conversation.campaign_id
    world_state = get_world_state(campaign_id)
    return {"location": (world_state.location if world_state else "") or ""}


@router.put("/conversations/{conversation_id}/location", status_code=200)
def update_location(conversation_id: int, location: str = Body(..., embed=True)) -> dict[str, str]:
    with db_session() as s:
        conversation = _get_conversation(s, conversation_id)
        campaign_id = conversation.campaign_id
    set_location(campaign_id, location)
    logger.info(f"📍 Location saved to campaign {campaign_id}")
    return {"message": "Location updated"}


@router.put('/messages/{message_id}', status_code=200)
def edit_message(message_id: UUID = Path(...), content: str = Body(..., embed=True)) -> dict[str, str]:
    with db_session() as s:
        message = s.query(Message).filter(Message.id == message_id).first()
        if not message:
            raise HTTPException(status_code=404, detail="Message not found")
        conversation_id = message.conversation_id
        message.content = content

    # A live socket session keeps its own detached Conversation snapshot; its
    # transient message_buffer must mirror the DB or agents keep seeing the
    # old content.
    live = get_live_conversation(conversation_id)
    if live is not None:
        for buffered in getattr(live, "message_buffer", []):
            if str(buffered.id) == str(message_id):
                buffered.content = content
                logger.info(f"🧹 Patched message {message_id} in buffer of conversation {conversation_id}")

    logger.info(f"📝 Message {message_id} edited")
    return {"message": "Message edited"}


@router.delete('/messages/{message_id}', status_code=200)
def delete_message(message_id: UUID = Path(...)) -> dict[str, str]:
    with db_session() as s:
        message = s.query(Message).filter(Message.id == message_id).first()
        if not message:
            raise HTTPException(status_code=404, detail="Message not found")
        conversation_id = message.conversation_id
        s.delete(message)

    live = get_live_conversation(conversation_id)
    if live is not None:
        buffer = getattr(live, "message_buffer", [])
        pruned = [m for m in buffer if str(m.id) != str(message_id)]
        if len(pruned) != len(buffer):
            live.message_buffer = pruned
            logger.info(f"🧹 Pruned message {message_id} from buffer of conversation {conversation_id}")

    logger.info(f"📝 Message {message_id} deleted")
    return {"message": "Message deleted"}
