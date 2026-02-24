import uuid
from datetime import datetime, timezone
from logging import getLogger

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Table, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import relationship

from database.postgres_connection import Base, session
from database.models import Player, Character

logger = getLogger(__name__)

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
    """🎭 A conversation between a player and one or more characters.

    Tracks participants, stores every message, and can be converted
    straight into an ``AgentSwarmState`` dict for graph execution.
    """

    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=True)
    player_id = Column(Integer, ForeignKey("players.id"), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True),nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True),nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    location = Column(String, nullable=True)
    story_background = Column(Text, nullable=True)
    lore_world = Column(String, nullable=True)

    # --- relationships ---------------------------------------------------

    player = relationship("Player", lazy="selectin")
    characters = relationship("Character", secondary=conversation_characters, lazy="selectin")
    messages = relationship("Message", back_populates="conversation", order_by="Message.created_at", cascade="all, delete-orphan", lazy="selectin")

    # ------------------------------------------------------------------
    # Participant helpers
    # ------------------------------------------------------------------

    def add_character(self, character: object) -> None:
        """🎭 Add a character to this conversation's participants."""
        if character not in self.characters:
            self.characters.append(character)
            logger.info(
                f"🎭 Character '{character.name}' joined conversation {self.id}"
            )

    # ------------------------------------------------------------------
    # Message helpers
    # ------------------------------------------------------------------

    def add_message(self, role: str, content: str, speaker_name: str | None = None) -> "Message | None":
        """💬 Append a new message to this conversation.

        Args:
            role: One of ``"human"``, ``"ai"``, or ``"system"``.
            content: The message body.
            speaker_name: Optional display name (character / player).

        Returns:
            The newly created Message instance, or None if skipped (duplicate UUID).
        """
        msg = Message(role=role, content=content, speaker_name=speaker_name)
        self.messages.append(msg)
        session.add(msg)
        session.add(self)
        try:
            session.commit()
            logger.info(
                f"💬 [{role}] message added to conversation {self.id} "
                f"(speaker={speaker_name})"
            )
            return msg
        except IntegrityError as exc:
            session.rollback()
            
            if "duplicate key" in str(exc).lower() or "unique constraint" in str(exc).lower():
                self.messages.remove(msg)
                logger.warning(f"⚠️ Duplicate message UUID, skipping add (id={msg.id})")
                return None
            raise exc

    # ------------------------------------------------------------------
    # AgentSwarmState conversion
    # ------------------------------------------------------------------

    def langchain_messages(self) -> list[AnyMessage]:
        return [msg.to_langchain_message() for msg in self.messages]


    @classmethod
    def create(cls, player: Player, characters: list[Character]) -> "Conversation":
        """🎭 Create a new conversation between a player and one or more characters."""
        conversation = cls(player=player)
        for character in characters:
            conversation.add_character(character)
        conversation.title = f"{player.name} {', '.join([c.name for c in characters])}"
        session.add(conversation)
        session.commit()
        return conversation

    def __repr__(self) -> str:
        return (
            f"<Conversation(id={self.id}, title='{self.title}', "
            f"characters={len(self.characters)}, messages={len(self.messages)})>"
        )
