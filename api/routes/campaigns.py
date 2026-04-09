import logging

from fastapi import APIRouter, Body
from fastapi.exceptions import HTTPException

from database.models import Campaign, Conversation
from database.postgres_connection import session
from database.graphiti_utils import wipe_campaign_memories

logger = logging.getLogger(__name__)

campaigns_router = APIRouter(prefix="/campaigns")


@campaigns_router.get("")
def list_campaigns() -> list[dict[str, object]]:
    campaigns = session.query(Campaign).order_by(Campaign.id.desc()).all()
    return [
        {
            "id": c.id,
            "name": c.name,
            "lore_world": c.lore_world,
            "conversation_count": len(c.conversations),
            "created_at": c.created_at.isoformat(),
        }
        for c in campaigns
    ]


@campaigns_router.get("/{campaign_id}")
def get_campaign(campaign_id: int) -> dict[str, object]:
    campaign = session.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    npcs: dict[int, dict[str, object]] = {}
    for conv in campaign.conversations:
        for char in conv.characters:
            if char.id not in npcs:
                npcs[char.id] = {"id": char.id, "name": char.name}

    return {
        "id": campaign.id,
        "name": campaign.name,
        "lore_world": campaign.lore_world,
        "created_at": campaign.created_at.isoformat(),
        "conversations": [
            {
                "id": conv.id,
                "title": conv.title or f"Conversation #{conv.id}",
                "created_at": conv.created_at.isoformat(),
            }
            for conv in campaign.conversations
        ],
        "npcs": list(npcs.values()),
    }


@campaigns_router.post("", status_code=201)
def create_campaign(
    name: str = Body(..., embed=True),
    lore_world: str = Body(..., embed=True),
) -> dict[str, object]:
    existing = session.query(Campaign).filter(Campaign.name == name).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Campaign '{name}' already exists")

    campaign = Campaign(name=name, lore_world=lore_world)
    session.add(campaign)
    session.commit()
    logger.info(f"🏰 Created campaign '{name}' with lore_world='{lore_world}'")
    return {
        "id": campaign.id,
        "name": campaign.name,
        "lore_world": campaign.lore_world,
        "created_at": campaign.created_at.isoformat(),
        "conversations": [],
        "npcs": [],
    }


@campaigns_router.delete("/{campaign_id}")
async def delete_campaign(campaign_id: int) -> dict[str, str]:
    campaign = session.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    try:
        await wipe_campaign_memories(campaign_id)
    except Exception as exc:
        logger.error(f"❌ Failed to wipe Graphiti memories for campaign {campaign_id}: {exc}")

    campaign_name = campaign.name
    session.delete(campaign)
    session.commit()
    logger.info(f"🗑️ Campaign {campaign_id} ('{campaign_name}') deleted")
    return {"message": f"Campaign '{campaign_name}' deleted"}
