from datetime import datetime, timezone
from logging import getLogger

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint

from database.postgres_connection import Base

logger = getLogger(__name__)


class CampaignMechanic(Base):
    """⚙️ One negotiated custom mechanics document for a campaign.

    Written by the campaign-negotiation agent once the organizer approves a
    design; read by the DM at play time. Each row is a self-contained
    markdown document carrying its own scope and supersession header, e.g.
    "The Leash -- Ma Yulan Mechanics". Simple per-character roll mechanics
    belong in CharacterStatusEffect instead; this table holds the systems
    too complex for structured fields.
    """

    __tablename__ = "campaign_mechanics"
    __table_args__ = (
        UniqueConstraint("campaign_id", "title", name="uq_campaign_mechanics_campaign_title"),
    )

    id = Column(Integer, primary_key=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=False, index=True)
    title = Column(String, nullable=False)
    content = Column(Text, nullable=False)
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

    def __repr__(self) -> str:
        return (
            f"<CampaignMechanic(id={self.id}, campaign_id={self.campaign_id}, "
            f"title='{self.title}')>"
        )
