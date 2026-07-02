from datetime import datetime, timezone
from logging import getLogger

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from database.postgres_connection import Base

logger = getLogger(__name__)


class WorldState(Base):
    """🌍 The live, advancing world state for a campaign (1:1 with Campaign).

    Holds the current scene location and narrative time -- the bits that
    change during play. Unlike the static ``Campaign`` metadata, these are
    mutated by the DM canon manager as scenes move. A campaign has at most
    one row; access it through ``Campaign.world_state`` or the
    ``ensure_world_state`` helper.
    """

    __tablename__ = "world_state"

    id = Column(Integer, primary_key=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=False, unique=True, index=True)
    location = Column(String, nullable=False, default="")
    world_clock = Column(String, nullable=False, default="")
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

    campaign = relationship("Campaign", back_populates="world_state")

    def __repr__(self) -> str:
        return (
            f"<WorldState(campaign_id={self.campaign_id}, "
            f"location='{self.location}', world_clock='{self.world_clock}')>"
        )


class QuestThread(Base):
    """🧵 An open narrative loop the DM is tracking for a campaign.

    Threads are enumerable canon ("the missing children", "Rusk's debt") so
    the planner can surface hooks naturally and nothing rots forgotten.
    """

    __tablename__ = "quest_threads"

    STATUSES = ("open", "resolved", "abandoned")

    id = Column(Integer, primary_key=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=False, index=True)
    title = Column(String, nullable=False)
    status = Column(String, nullable=False, default="open")  # open | resolved | abandoned
    notes = Column(Text, nullable=False, default="")
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
            f"<QuestThread(id={self.id}, campaign_id={self.campaign_id}, "
            f"title='{self.title}', status='{self.status}')>"
        )


class FactionClock(Base):
    """⏰ A progress clock for a faction's offscreen agenda.

    When ``ticks_current`` reaches ``ticks_max`` the faction's goal comes to
    pass and the clock is marked completed.
    """

    __tablename__ = "faction_clocks"

    STATUSES = ("active", "completed", "stalled")

    id = Column(Integer, primary_key=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=False, index=True)
    faction_name = Column(String, nullable=False)
    goal = Column(Text, nullable=False)
    ticks_current = Column(Integer, nullable=False, default=0)
    ticks_max = Column(Integer, nullable=False, default=6)
    next_move = Column(Text, nullable=False, default="")
    status = Column(String, nullable=False, default="active")  # active | completed | stalled
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

    @property
    def filled(self) -> bool:
        return self.ticks_current >= self.ticks_max

    def __repr__(self) -> str:
        return (
            f"<FactionClock(id={self.id}, faction='{self.faction_name}', "
            f"clock={self.ticks_current}/{self.ticks_max}, status='{self.status}')>"
        )
