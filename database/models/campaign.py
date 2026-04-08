from datetime import datetime, timezone
from logging import getLogger

from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.orm import relationship

from hephaestus.settings import settings
from database.postgres_connection import Base

logger = getLogger(__name__)


class Campaign(Base):
    """🏰 A campaign groups conversations under a shared lore world."""

    __tablename__ = "campaigns"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, unique=True)
    lore_world = Column(String, nullable=False, default=settings.PLACEHOLDER_LORE_WORLD)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    conversations = relationship(
        "Conversation",
        back_populates="campaign",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return (
            f"<Campaign(id={self.id}, name='{self.name}', "
            f"lore_world='{self.lore_world}', conversations={len(self.conversations)})>"
        )
