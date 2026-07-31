import logging

from fastapi import APIRouter, Body
from fastapi.exceptions import HTTPException

from database.models import Campaign, CharacterMemory, DMSecret, PlayerPreference, World, WorldEvent, WorldState
from database.postgres_connection import db_session
from utils.prompts import placeholder_location, placeholder_scenario

logger = logging.getLogger(__name__)

campaigns_router = APIRouter(prefix="/campaigns")


@campaigns_router.get("")
def list_campaigns() -> list[dict[str, object]]:
    with db_session() as s:
        campaigns = s.query(Campaign).order_by(Campaign.id.desc()).all()
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
    with db_session() as s:
        campaign = s.query(Campaign).filter(Campaign.id == campaign_id).first()
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
    with db_session() as s:
        existing = s.query(Campaign).filter(Campaign.name == name).first()
        if existing:
            raise HTTPException(status_code=409, detail=f"Campaign '{name}' already exists")

        world = s.query(World).filter(World.name == lore_world.strip()).first()
        if world is None:
            raise HTTPException(status_code=400, detail=f"Unknown lore world '{lore_world}'")

        campaign = Campaign(name=name, world_id=world.id, story_background=placeholder_scenario)
        # Seed the 1:1 world state with a placeholder scene location; narrative
        # time starts empty and advances during play.
        campaign.world_state = WorldState(location=placeholder_location)
        s.add(campaign)
        s.flush()
        response = {
            "id": campaign.id,
            "name": campaign.name,
            "lore_world": campaign.lore_world,
            "created_at": campaign.created_at.isoformat(),
            "conversations": [],
            "npcs": [],
        }
    logger.info(f"🏰 Created campaign '{name}' with lore_world='{lore_world}'")
    return response


@campaigns_router.delete("/{campaign_id}")
def delete_campaign(campaign_id: int) -> dict[str, str]:
    with db_session() as s:
        exists = s.query(Campaign.id).filter(Campaign.id == campaign_id).first()
        if not exists:
            raise HTTPException(status_code=404, detail="Campaign not found")

    try:
        for model in (CharacterMemory, WorldEvent, DMSecret, PlayerPreference):
            model.wipe_campaign(campaign_id)
    except Exception:
        logger.exception(f"💥 Failed to wipe knowledge rows for campaign {campaign_id}")

    with db_session() as s:
        campaign = s.query(Campaign).filter(Campaign.id == campaign_id).first()
        campaign_name = campaign.name
        s.delete(campaign)
    logger.info(f"🗑️ Campaign {campaign_id} ('{campaign_name}') deleted")
    return {"message": f"Campaign '{campaign_name}' deleted"}
