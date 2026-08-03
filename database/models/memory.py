"""🧠📚 Campaign knowledge models: character memories (pgvector-recalled) and
the append-only streams (world events, DM secrets, player preferences).
"""
import asyncio
from datetime import datetime, timezone
from logging import getLogger
from typing import ClassVar

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, DateTime, ForeignKey, Integer, Text
from sqlalchemy.exc import SQLAlchemyError

from database.postgres_connection import Base, db_session
from database.session_utils import embedder
from hephaestus.settings import settings

logger = getLogger(__name__)

EMBED_DIM = settings.memory.embed_dim
recall_cfg = settings.memory.recall


class CharacterMemory(Base):
    """🧠 One distilled memory an NPC formed during a campaign.

    Written by the scene epilogue when a scene ends; recalled via pgvector
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

    @property
    def simple_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "campaign_id": self.campaign_id,
            "character_id": self.character_id,
            "title": self.title,
            "content": self.content,
        }

    @classmethod
    def filter_by_campaign(cls, campaign_id: int, character_id: int | None = None) -> list["CharacterMemory"]:
        filters = [cls.campaign_id == campaign_id]
        if character_id is not None:
            filters.append(cls.character_id == character_id)
        with db_session() as s:
            return s.query(cls).filter(*filters).order_by(cls.created_at).all()

    @classmethod
    def add_memory(cls, campaign_id: int, character_id: int, title: str, content: str) -> "CharacterMemory | None":
        """💾 Embed and store one memory; None if the commit failed."""
        memory = cls(campaign_id=campaign_id, character_id=character_id, title=title, content=content)
        memory.embedding = embedder.embed_query(content)
        return memory.save()

    def update_memory_content(self, content: str) -> "CharacterMemory | None":
        self.content = content
        self.embedding = embedder.embed_query(content)
        return self.save()

    @classmethod
    async def recall(cls, campaign_id: int, character_id: int, query: str) -> str:
        """🔍 pgvector top-K similar to *query* plus the most recent few,
        deduplicated, rendered newline-joined (oldest first)."""
        vector = await embedder.aembed_query(query)
        return await asyncio.to_thread(cls._recall, campaign_id, character_id, vector)

    @classmethod
    async def recall_by_vector(cls, campaign_id: int, character_id: int, vector: list[float]) -> str:
        """🔍 Same recall as ``recall`` but with a precomputed query vector --
        the DM embeds the player's message once per turn and every responding
        NPC reuses it instead of re-embedding."""
        return await asyncio.to_thread(cls._recall, campaign_id, character_id, vector)

    @classmethod
    def _recall(cls, campaign_id: int, character_id: int, vector: list[float]) -> str:
        with db_session() as s:
            base = s.query(cls).filter(cls.campaign_id == campaign_id, cls.character_id == character_id)
            similar = (
                base.filter(cls.embedding.isnot(None))
                .order_by(cls.embedding.l2_distance(vector))
                .limit(recall_cfg.memories_top_k)
                .all()
            )
            recent = base.order_by(cls.created_at.desc()).limit(recall_cfg.memories_recent).all()
        seen = {m.id: m.content for m in [*similar, *recent]}
        logger.info(f"🧠 Recalled {len(seen)} memories for character {character_id} (campaign {campaign_id})")
        return "\n".join(content for _, content in sorted(seen.items()))

    def __repr__(self) -> str:
        return (
            f"<CharacterMemory(id={self.id}, campaign_id={self.campaign_id}, "
            f"character_id={self.character_id})>"
        )


class CampaignStream(Base):
    """🌊 Append-only campaign knowledge stream: one ``content`` row per fact.

    Subclasses differ only in table name and how many rows the DM context
    gets by default (``relevant_top_k`` vector hits plus ``recent_limit``
    recency rows). Every row is embedded at write time (best-effort) so
    ``relevant_and_recent`` can surface topically related facts instead of
    only the freshest ones.
    """

    __abstract__ = True

    id = Column(Integer, primary_key=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=False, index=True)
    content = Column(Text, nullable=False)
    embedding = Column(Vector(EMBED_DIM), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    recent_limit: ClassVar[int] = 5
    relevant_top_k: ClassVar[int] = 8

    @classmethod
    async def add_items(cls, campaign_id: int, items: list[str]) -> None:
        """💾 Append one row per non-empty item, embedding each for recall.

        Fail-secure: an embedder failure stores the rows with NULL embeddings
        (recall simply skips them until a backfill) -- a fact must never be
        dropped because the embedder hiccuped.
        """
        items = [i.strip() for i in items if i and i.strip()]
        if not items:
            return

        try:
            vectors: list[list[float] | None] = await embedder.aembed_documents(items)
        except Exception:
            logger.exception(
                f"💥 Embedding failed for {len(items)} {cls.__name__} item(s); storing without vectors"
            )
            vectors = [None] * len(items)

        def _insert() -> bool:
            try:
                with db_session() as s:
                    s.add_all([
                        cls(campaign_id=campaign_id, content=item, embedding=vector)
                        for item, vector in zip(items, vectors)
                    ])
                return True
            except SQLAlchemyError:
                logger.error(f"❌ Failed to save {len(items)} {cls.__name__} row(s) for campaign {campaign_id}")
                return False

        if await asyncio.to_thread(_insert):
            logger.info(f"💾 Saved {len(items)} {cls.__name__} row(s) for campaign {campaign_id}")

    @classmethod
    def recent(cls, campaign_id: int, limit: int | None = None) -> str:
        """The most recent stream rows, newline-joined oldest-first."""
        with db_session() as s:
            rows = (
                s.query(cls)
                .filter(cls.campaign_id == campaign_id)
                .order_by(cls.id.desc())
                .limit(limit or cls.recent_limit)
                .all()
            )
        return "\n".join(r.content for r in reversed(rows))

    @classmethod
    def relevant(cls, campaign_id: int, vector: list[float], top_k: int | None = None) -> list["CampaignStream"]:
        """🔍 pgvector top-K rows closest to *vector* (rows with embeddings only)."""
        with db_session() as s:
            return (
                s.query(cls)
                .filter(cls.campaign_id == campaign_id)
                .filter(cls.embedding.isnot(None))
                .order_by(cls.embedding.l2_distance(vector))
                .limit(top_k or cls.relevant_top_k)
                .all()
            )

    @classmethod
    def relevant_and_recent(
        cls,
        campaign_id: int,
        vector: list[float],
        top_k: int | None = None,
        recent: int | None = None,
    ) -> str:
        """🔍 Vector top-K unioned with the freshest rows, deduplicated and
        rendered newline-joined oldest-first -- brand-new facts always
        surface even when they are not (yet) topically close to the query."""
        similar = cls.relevant(campaign_id, vector, top_k)
        with db_session() as s:
            recent_rows = (
                s.query(cls)
                .filter(cls.campaign_id == campaign_id)
                .order_by(cls.id.desc())
                .limit(recent if recent is not None else cls.recent_limit)
                .all()
            )
        seen = {row.id: row.content for row in [*similar, *recent_rows]}
        logger.info(
            f"🔍 Recalled {len(seen)} {cls.__name__} row(s) for campaign {campaign_id} "
            f"({len(similar)} relevant + {len(recent_rows)} recent)"
        )
        return "\n".join(content for _, content in sorted(seen.items()))

    def __repr__(self) -> str:
        return f"<{type(self).__name__}(id={self.id}, campaign_id={self.campaign_id})>"


class WorldEvent(CampaignStream):
    """🌍 Something that became true in the campaign world."""

    __tablename__ = "world_events"

    recent_limit: ClassVar[int] = recall_cfg.events_recent
    relevant_top_k: ClassVar[int] = recall_cfg.events_top_k


class DMSecret(CampaignStream):
    """🤫 DM-only secret knowledge for a campaign (never shown to NPCs)."""

    __tablename__ = "dm_secrets"

    recent_limit: ClassVar[int] = recall_cfg.secrets_recent
    relevant_top_k: ClassVar[int] = recall_cfg.secrets_top_k


class PlayerPreference(CampaignStream):
    """🎯 A learned player preference (pacing/tone signal for the DM)."""

    __tablename__ = "player_preferences"

    recent_limit: ClassVar[int] = recall_cfg.prefs_recent
