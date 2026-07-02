from datetime import datetime, timezone
from logging import getLogger

from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
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
    # Static story premise for the campaign (set at creation, editable via the UI).
    story_background = Column(Text, nullable=False, default="")
    contract = Column(JSONB, nullable=False, default=lambda: dict(settings.default_contract.model_dump()))

    conversations = relationship(
        "Conversation",
        back_populates="campaign",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    # 1:1 live world state (current scene + narrative time) -- see WorldState.
    world_state = relationship(
        "WorldState",
        back_populates="campaign",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    @property
    def location(self) -> str:
        """📍 Current scene location, read from the campaign's world state."""
        return self.world_state.location if self.world_state else ""

    @property
    def world_clock(self) -> str:
        """🕰️ Narrative time, read from the campaign's world state."""
        return self.world_state.world_clock if self.world_state else ""

    def render_contract(self) -> str:
        """📜 Render the story-contract dials as a prompt-friendly block.

        Always walks the canonical key order so downstream prompts stay stable
        regardless of how the JSONB column is stored; missing dials show as
        ``(unset)`` rather than silently disappearing.
        """
        contract = self.contract
        lines = "\n".join(
            f"  - {key}: {contract.get(key, '(unset)')}" for key in self.contract
        ) or "  (none)"
        return f"contract:\n{lines}"

    def __repr__(self) -> str:
        return (
            f"<Campaign(id={self.id}, name='{self.name}', "
            f"lore_world='{self.lore_world}', conversations={len(self.conversations)})>"
        )
