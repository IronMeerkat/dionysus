from datetime import datetime, timezone
from logging import getLogger

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import relationship

from database.postgres_connection import Base, db_session
from hephaestus.settings import settings

logger = getLogger(__name__)

EMBED_DIM = settings.memory.embed_dim


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

    @property
    def entry_count(self) -> int:
        """📚 Entry count via its own task session -- works on detached Worlds."""
        if self.id is None:
            return 0
        with db_session() as s:
            return s.query(func.count(LoreEntry.id)).filter(LoreEntry.world_id == self.id).scalar() or 0

    @property
    def simple_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "entry_count": self.entry_count,
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def get_world_by_name(cls, name: str) -> "World":
        return cls.get(name=name)

    def __repr__(self) -> str:
        return f"<World(id={self.id}, name='{self.name}')>"


class LoreEntry(Base):
    """📜 A single lore document -- the content is a full markdown file."""

    __tablename__ = "lore_entries"

    id = Column(Integer, primary_key=True)
    world_id = Column(Integer, ForeignKey("worlds.id"), nullable=False, index=True)
    title = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    embedding = Column(Vector(EMBED_DIM), nullable=True)
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

    @property
    def simple_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "title": self.title,
            "content": self.content,
            "world_name": self.world.name,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def preview_entries(cls, world: "World") -> list[dict[str, object]]:
        preview_chars = settings.memory.recall.lore_preview_chars
        with db_session() as s:
            entries = s.query(cls).filter(cls.world_id == world.id).order_by(cls.created_at).all()
            return [
                {
                    "id": e.id,
                    "title": e.title,
                    "preview": " ".join(e.content.split())[: preview_chars],
                    "created_at": e.created_at.isoformat(),
                    "updated_at": e.updated_at.isoformat(),
                }
                for e in entries
            ]

    @classmethod
    def filter_by_world(cls, world: "World") -> list["LoreEntry"]:
        with db_session() as s:
            return s.query(cls).filter(cls.world_id == world.id).order_by(cls.created_at).all()

    @staticmethod
    def embedding_text(title: str, content: str) -> str:
        """🧬 The exact payload embedded for an entry -- keep every write
        path and the backfill script on this one shape so vectors are
        comparable."""
        return f"# {title.strip()}\n\n{content.strip()}"

    @classmethod
    def search(cls, world: "World", vector: list[float], top_k: int) -> list["LoreEntry"]:
        """🔍 Euclidean-similarity recall over a world's embedded entries.

        Only rows with an embedding participate; unembedded entries are
        invisible until the backfill script (or a re-save) vectorizes them.
        """
        with db_session() as s:
            return (
                s.query(cls)
                .filter(cls.world_id == world.id)
                .filter(cls.embedding.isnot(None))
                .order_by(cls.embedding.l2_distance(vector))
                .limit(top_k)
                .all()
            )

    @classmethod
    def get_entry(cls, entry_id: int) -> "LoreEntry":
        with db_session() as s:
            return s.query(cls).filter(cls.id == entry_id).first()

    def __repr__(self) -> str:
        return f"<LoreEntry(id={self.id}, world_id={self.world_id}, title='{self.title}')>"
