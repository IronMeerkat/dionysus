from datetime import datetime, timezone
from logging import getLogger

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from database.postgres_connection import Base

logger = getLogger(__name__)


class World(Base):
    """🌍 A lore world: a named setting that owns a library of markdown lore entries."""

    __tablename__ = "worlds"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, unique=True, index=True)
    description = Column(Text, nullable=False, default="")
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

    # No eager loading: entries carry full markdown content, so pulling them
    # implicitly on every World query would drag the whole library along.
    entries = relationship(
        "LoreEntry",
        back_populates="world",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<World(id={self.id}, name='{self.name}')>"


class LoreEntry(Base):
    """📜 A single lore document -- the content is a full markdown file."""

    __tablename__ = "lore_entries"

    id = Column(Integer, primary_key=True)
    world_id = Column(Integer, ForeignKey("worlds.id"), nullable=False, index=True)
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

    world = relationship("World", back_populates="entries")

    def __repr__(self) -> str:
        return f"<LoreEntry(id={self.id}, world_id={self.world_id}, title='{self.title}')>"
