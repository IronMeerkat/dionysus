from datetime import datetime, timezone
from logging import getLogger

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, DateTime, ForeignKey, Integer, Text

from database.postgres_connection import Base
from hephaestus.settings import settings

logger = getLogger(__name__)

EMBED_DIM = settings.memory.embed_dim


class CharacterMemory(Base):
    """🧠 One distilled memory an NPC formed during a campaign.

    Written by the significance filter after a turn; recalled via pgvector
    similarity (plus recency) when the NPC narrates.
    """

    __tablename__ = "character_memories"

    id = Column(Integer, primary_key=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=False, index=True)
    character_id = Column(Integer, ForeignKey("characters.id"), nullable=False, index=True)
    title = Column(Text, nullable=False, default="")
    content = Column(Text, nullable=False)
    embedding = Column(Vector(EMBED_DIM), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:
        return (
            f"<CharacterMemory(id={self.id}, campaign_id={self.campaign_id}, "
            f"character_id={self.character_id})>"
        )


class WorldEvent(Base):
    """🌍 Something that became true in the campaign world (append-only stream)."""

    __tablename__ = "world_events"

    id = Column(Integer, primary_key=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=False, index=True)
    content = Column(Text, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:
        return f"<WorldEvent(id={self.id}, campaign_id={self.campaign_id})>"


class DMSecret(Base):
    """🤫 DM-only secret knowledge for a campaign (never shown to NPCs)."""

    __tablename__ = "dm_secrets"

    id = Column(Integer, primary_key=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=False, index=True)
    content = Column(Text, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:
        return f"<DMSecret(id={self.id}, campaign_id={self.campaign_id})>"


class PlayerPreference(Base):
    """🎯 A learned player preference (pacing/tone signal for the DM)."""

    __tablename__ = "player_preferences"

    id = Column(Integer, primary_key=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=False, index=True)
    content = Column(Text, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:
        return f"<PlayerPreference(id={self.id}, campaign_id={self.campaign_id})>"
