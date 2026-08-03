"""🧭 Routing exemplars: labeled, embedded player messages used for
OOC-vs-story routing by nearest-neighbor vote -- the cheap alternative to a
per-turn LLM intent classification hop.

Seeded by ``scripts/seed_routing_exemplars.py``; consumed by
``agents.dungeon_master.intent.route_by_exemplars``.
"""
from logging import getLogger

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, Integer, String, Text

from database.postgres_connection import Base, db_session
from hephaestus.settings import settings

logger = getLogger(__name__)

EMBED_DIM = settings.memory.embed_dim

LABEL_OOC = "ooc"
LABEL_STORY = "story"
LABELS = (LABEL_OOC, LABEL_STORY)


class RoutingExemplar(Base):
    """🏷️ One labeled example player message with its embedding.

    Small table (a hundred-ish rows), so no ivfflat index -- a sequential
    scan over a handful of 1024-dim vectors is already microseconds.
    """

    __tablename__ = "routing_exemplars"

    id = Column(Integer, primary_key=True)
    label = Column(String, nullable=False, index=True)  # "ooc" | "story"
    text = Column(Text, nullable=False)
    embedding = Column(Vector(EMBED_DIM), nullable=False)

    @classmethod
    def nearest(cls, vector: list[float], top_k: int) -> list[tuple["RoutingExemplar", float]]:
        """🔍 The top-K closest exemplars with their L2 distances, nearest first."""
        distance = cls.embedding.l2_distance(vector).label("distance")
        with db_session() as s:
            return s.query(cls, distance).order_by(distance).limit(top_k).all()

    @classmethod
    def count(cls) -> int:
        with db_session() as s:
            return s.query(cls).count()

    def __repr__(self) -> str:
        return f"<RoutingExemplar(id={self.id}, label='{self.label}')>"
