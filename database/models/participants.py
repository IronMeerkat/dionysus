from datetime import datetime, timezone
from logging import getLogger

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from database.postgres_connection import Base

logger = getLogger(__name__)


# ------------------------------------------------------------------
# Live participant state
# ------------------------------------------------------------------
#
# The mutable, non-relational game-mechanical state of a participant in a
# campaign -- stats, status effects, modifiers, freeform notes -- lives in a
# single JSONB ``state`` blob so the schema stays flexible as a campaign grows.
# Foreign keys (campaign + player/character) are real columns; everything else
# is JSON. An empty blob means "no tracked mechanical state" and the prompts
# behave as a pure narrative game, so this is opt-in per campaign.

DEFAULT_PARTICIPANT_STATE: dict = {
    "stats": {},          # vitals/attributes, e.g. {"hp": 10, "max_hp": 10, "ac": 12, "speed": 30}
    "status_effects": [],  # active conditions, e.g. ["poisoned", "frightened"]
    "modifiers": {},      # situational bonuses/penalties, e.g. {"attack": 2, "stealth": -1}
    "notes": "",          # freeform DM notes about this participant's state
}


class CampaignPlayer(Base):
    """🎲 A player's live, per-campaign mechanical state.

    One row per (campaign, player). The ``state`` JSONB blob holds stats,
    status effects, modifiers and notes -- the things that change during play.
    The DM canon manager applies structured patches to it; prompts render it.
    """

    __tablename__ = "campaign_players"
    __table_args__ = (
        UniqueConstraint("campaign_id", "player_id", name="uq_campaign_players_campaign_player"),
    )

    id = Column(Integer, primary_key=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=False, index=True)
    player_id = Column(Integer, ForeignKey("players.id"), nullable=False, index=True)
    state = Column(JSONB, nullable=False, default=lambda: dict(DEFAULT_PARTICIPANT_STATE))
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    campaign = relationship("Campaign", lazy="selectin")
    player = relationship("Player", lazy="selectin")

    def __repr__(self) -> str:
        return (
            f"<CampaignPlayer(campaign_id={self.campaign_id}, "
            f"player_id={self.player_id}, state_keys={list((self.state or {}).keys())})>"
        )


class CampaignNPC(Base):
    """🎭 An NPC's live, per-campaign mechanical state.

    One row per (campaign, character). Mirrors ``CampaignPlayer`` for
    non-player characters -- wounds, conditions, modifiers the DM tracks so
    NPCs react consistently and the continuity checker can catch a dead or
    unconscious NPC trying to speak.
    """

    __tablename__ = "campaign_npcs"
    __table_args__ = (
        UniqueConstraint("campaign_id", "character_id", name="uq_campaign_npcs_campaign_character"),
    )

    id = Column(Integer, primary_key=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=False, index=True)
    character_id = Column(Integer, ForeignKey("characters.id"), nullable=False, index=True)
    state = Column(JSONB, nullable=False, default=lambda: dict(DEFAULT_PARTICIPANT_STATE))
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    campaign = relationship("Campaign", lazy="selectin")
    character = relationship("Character", lazy="selectin")

    def __repr__(self) -> str:
        return (
            f"<CampaignNPC(campaign_id={self.campaign_id}, "
            f"character_id={self.character_id}, "
            f"state_keys={list((self.state or {}).keys())})>"
        )
