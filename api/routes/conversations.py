import logging

from fastapi import APIRouter, Body, Query
from fastapi.exceptions import HTTPException

from database.models import Conversation
from database.postgres_connection import db_session

logger = logging.getLogger(__name__)

conversations_router = APIRouter(prefix='/conversations')


@conversations_router.get("/list")
def list_conversations(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict[str, object]:
    with db_session() as s:
        total = s.query(Conversation).count()
        conversations = (
            s.query(Conversation)
            .order_by(Conversation.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        items = [{"id": c.id, "title": c.title} for c in conversations]
    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
    }


@conversations_router.put("/{conversation_id}/rename")
def rename_conversation( conversation_id: int, title: str = Body(..., embed=True)) -> dict[str, object]:
    with db_session() as s:
        conversation = s.get(Conversation, conversation_id)
        if not conversation:
            raise HTTPException(status_code=404, detail=f"Conversation {conversation_id} not found")
        conversation.title = title
    logger.info(f"✏️ Conversation {conversation_id} renamed to '{title}'")
    return {"id": conversation.id, "title": conversation.title}


@conversations_router.delete("/{conversation_id}")
def delete_conversation(conversation_id: int) -> dict[str, str]:
    with db_session() as s:
        conversation = s.get(Conversation, conversation_id)
        if not conversation:
            raise HTTPException(status_code=404, detail=f"Conversation {conversation_id} not found")
        s.delete(conversation)
    logger.info(f"🗑️ Conversation {conversation_id} deleted")
    return {"detail": f"Conversation {conversation_id} deleted"}
