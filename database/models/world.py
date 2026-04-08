from datetime import datetime, timezone
from logging import getLogger

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from database.postgres_connection import Base
from database.graphiti_utils import make_group_id

logger = getLogger(__name__)


class World(Base):
    """🌍 A lore world -- the Postgres anchor for a Graphiti lore namespace.

    Each world maps 1-to-1 with a Graphiti group_id via
    ``make_group_id("lore", name)``.  Conversations reference a world
    to pull the right lore context at runtime.
    """

    __tablename__ = "worlds"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, unique=True, index=True)
    description = Column(Text, default="")
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

    lore_entries = relationship(
        "LoreEntry",
        back_populates="world",
        order_by="LoreEntry.created_at",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    @property
    def graphiti_group_id(self) -> str:
        return make_group_id("lore", self.name)

    @classmethod
    def get_or_create(cls, name: str) -> "World":
        """Return existing world by name, or create a new one."""
        from database.postgres_connection import session

        world = session.query(cls).filter(cls.name == name).first()
        if world is None:
            world = cls(name=name)
            session.add(world)
            session.commit()
            logger.info(f"🌍 Created new world '{name}'")
        return world

    def __repr__(self) -> str:
        return f"<World(id={self.id}, name='{self.name}', entries={len(self.lore_entries)})>"


class LoreEntry(Base):
    """📜 A single authored lore entry, tracked in Postgres alongside its
    Graphiti ingestion.

    Stores the raw text the user/agent wrote so entries can be listed,
    browsed, and edited without querying the knowledge graph directly.
    """

    __tablename__ = "lore_entries"

    id = Column(Integer, primary_key=True)
    world_id = Column(Integer, ForeignKey("worlds.id"), nullable=False, index=True)
    title = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    category = Column(String, nullable=True)
    ingestion_status = Column(String, nullable=False, default="pending")
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

    world = relationship("World", back_populates="lore_entries")

    def __repr__(self) -> str:
        return (
            f"<LoreEntry(id={self.id}, title='{self.title}', "
            f"world='{self.world_id}', category='{self.category}')>"
        )
