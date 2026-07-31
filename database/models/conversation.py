import uuid
from datetime import datetime, timezone
from logging import getLogger

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Table, Text
from sqlalchemy.dialects.postgresql import UUID, insert as pg_insert
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import reconstructor, relationship

from database.postgres_connection import Base, Session, db_session
from database.models import Character
from hephaestus.settings import settings


logger = getLogger(__name__)

EMBED_DIM = settings.memory.embed_dim

# ------------------------------------------------------------------
# Association table: which characters participate in a conversation
# ------------------------------------------------------------------

conversation_characters = Table(
    "conversation_characters",
    Base.metadata,
    Column("conversation_id", Integer, ForeignKey("conversations.id"), primary_key=True),
    Column("character_id", Integer, ForeignKey("characters.id"), primary_key=True),
)


# ------------------------------------------------------------------
# Message
# ------------------------------------------------------------------


class Message(Base):
    """💬 A single message in a conversation.

    Stores the role (``human``, ``ai``, or ``system``), an optional
    speaker name, and the message content.  Messages are ordered by
    ``created_at`` within their parent conversation.
    """

    __tablename__ = "messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=False, index=True)
    role = Column(String, nullable=False)  # "human" | "ai" | "system"
    speaker_name = Column(String, nullable=True)  # e.g. character or player name
    content = Column(Text, nullable=False)
    embedding = Column(Vector(EMBED_DIM), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    conversation = relationship("Conversation", back_populates="messages")


    # ------------------------------------------------------------------
    # Conversion helpers
    # ------------------------------------------------------------------

    _ROLE_TO_CLS: dict[str, type[AnyMessage]] = {
        "human": HumanMessage,
        "ai": AIMessage,
        "system": SystemMessage,
    }

    def to_langchain_message(self) -> AnyMessage:
        """🔄 Convert this row into the matching langchain message type."""
        cls = self._ROLE_TO_CLS.get(self.role)
        if cls is None:
            raise ValueError(f"Unknown message role '{self.role}' in message {self.id}")

        kwargs: dict = {
            "id": str(self.id),
            "content": self.content,
            "type": self.role,
            "name": self.speaker_name
        }
        return cls(**kwargs)

    def __repr__(self) -> str:
        preview = (self.content[:40] + "…") if len(self.content) > 40 else self.content
        return (
            f"<Message(id={self.id}, role='{self.role}', "
            f"speaker='{self.speaker_name}', content='{preview}')>"
        )


# ------------------------------------------------------------------
# Conversation
# ------------------------------------------------------------------


class Conversation(Base):
    """🎭 A conversation between a player character and one or more NPCs.

    Tracks participants, stores every message, and can be converted
    straight into an ``AgentSwarmState`` dict for graph execution.

    The transient ``message_buffer`` holds an in-memory sliding window
    of langchain messages used by agents during graph execution.  It is
    NOT persisted to the database.
    """

    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=True)
    # The player character of this conversation: any character can be the PC,
    # and which one is decided here, at the conversation level.
    player_id = Column(Integer, ForeignKey("characters.id"), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True),nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True),nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=False, index=True)

    # --- relationships ---------------------------------------------------

    campaign = relationship("Campaign", back_populates="conversations", lazy="selectin")
    player = relationship("Character", lazy="selectin")
    characters = relationship("Character", secondary=conversation_characters, lazy="selectin")
    messages = relationship("Message", back_populates="conversation", order_by="Message.created_at", cascade="all, delete-orphan", lazy="selectin")

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._init_transient()

    @reconstructor
    def _init_transient(self) -> None:
        """Initialise non-persistent attributes.

        Called both from ``__init__`` (new instances) and by SQLAlchemy's
        ``@reconstructor`` hook (instances loaded from the DB).
        """
        self.message_buffer: list[AnyMessage] = []

    # ------------------------------------------------------------------
    # Participant helpers
    # ------------------------------------------------------------------

    def add_character(self, character: object) -> None:
        """🎭 Add a character to this conversation's participants.

        Always appends to the in-memory roster; when the conversation row
        already exists the association is also upserted in its own task
        session (live-snapshot Conversation objects are detached and cannot
        flush themselves). Deduplicates by character id, since the snapshot
        roster holds detached instances where identity comparison is useless.
        """
        if any(c.id == character.id for c in self.characters):
            return
        self.characters.append(character)
        logger.info(
            f"🎭 Character '{character.name}' joined conversation {self.id}"
        )
        if self.id is None:
            return  # transient: create() persists the roster via cascade
        try:
            with db_session() as s:
                s.execute(
                    pg_insert(conversation_characters)
                    .values(conversation_id=self.id, character_id=character.id)
                    .on_conflict_do_nothing()
                )
        except SQLAlchemyError:
            logger.error(
                f"❌ Failed to persist '{character.name}' joining conversation {self.id}"
            )

    # def remove_character(self, character: object) -> None:
    #     """👋 Remove a character from this conversation's participants."""
    #     if character in self.characters:
    #         self.characters.remove(character)
    #         session.add(self)
    #         session.commit()
    #         logger.info(
    #             f"👋 Character '{character.name}' left conversation {self.id}"
    #         )

    # ------------------------------------------------------------------
    # Message helpers
    # ------------------------------------------------------------------

    def add_message(self, role: str, content: str, speaker_name: str, _id: uuid.UUID | None = None, embedding: list[float] | None = None) -> "Message | None":
        """💬 Append a new message to this conversation.

        Args:
            role: One of ``"human"``, ``"ai"``, or ``"system"``.
            content: The message body.
            speaker_name: Display name (character / player).
            id: Optional UUID to use for this message. When provided the same
                UUID that was emitted to the frontend is written to the DB.
            embedding: Optional precomputed embedding vector for semantic
                recall of past play. Stored as-is on the row; ``None`` leaves
                the message unindexed by vector search.

        Returns:
            The newly created Message instance, or None if skipped (duplicate UUID).
        """
        _id = _id or uuid.uuid4()
        msg = Message(id=_id, conversation_id=self.id, role=role, content=content, speaker_name=speaker_name, embedding=embedding)
        # In-memory append keeps the live session's snapshot in sync with the
        # DB; the write below uses its own short-lived session (hand-rolled
        # rather than db_session() because a duplicate UUID is an expected,
        # quietly-skippable outcome, not a 💥 worth logging a trace for).
        self.messages.append(msg)
        # The relationship append back-referenced the (detached) conversation;
        # drop it so the writer session inserts the row by FK alone instead of
        # cascading the whole detached snapshot graph into itself.
        msg.conversation = self
        s = Session()
        try:
            s.add(msg)
            s.commit()
            logger.info(
                f"💬 [{role}] message added to conversation {self.id} "
                f"(speaker={speaker_name})"
            )
            return msg
        except IntegrityError as exc:
            s.rollback()
            if "duplicate key" in str(exc).lower() or "unique constraint" in str(exc).lower():
                self.messages.remove(msg)
                logger.warning(f"⚠️ Duplicate message UUID, skipping add (id={msg.id})")
                return None
            logger.exception(f"💥 Failed to persist message in conversation {self.id}")
            raise
        except SQLAlchemyError:
            s.rollback()
            logger.exception(f"💥 Failed to persist message in conversation {self.id}")
            raise
        finally:
            s.close()

    # ------------------------------------------------------------------
    # AgentSwarmState conversion
    # ------------------------------------------------------------------

    def langchain_messages(self) -> list[AnyMessage]:
        return [msg.to_langchain_message() for msg in self.messages]


    @classmethod
    def create(cls, player: Character, characters: list[Character], campaign_id: int) -> "Conversation":
        """🎭 Create a new conversation between a player character and one or more NPCs.

        The given characters are re-attached inside the task session (they
        are typically detached results of an earlier query), so only their
        ids/names need to be readable. The returned conversation is detached
        with its player/characters/messages loaded for immediate rendering.

        Scene location, story background, and narrative time are owned by the
        campaign / its world state, not the conversation, so they are not set here.
        """
        with db_session() as s:
            db_player = s.get(Character, player.id)
            db_characters = s.query(Character).filter(Character.id.in_([c.id for c in characters])).all()
            conversation = cls(player=db_player, campaign_id=campaign_id)

            for character in db_characters:
                conversation.add_character(character)
            conversation.title = f"{db_player.name} {', '.join([c.name for c in db_characters])}"
            s.add(conversation)
            s.flush()  # assign the id before detach
            _ = conversation.messages  # initialise the collection for the detached snapshot
        return conversation

    def __repr__(self) -> str:
        return (
            f"<Conversation(id={self.id}, title='{self.title}', "
            f"characters={len(self.characters)}, messages={len(self.messages)})>"
        )
