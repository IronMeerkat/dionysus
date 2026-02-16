from datetime import datetime, timezone
from logging import getLogger

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Table, Text
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

    id = Column(Integer, primary_key=True)
    conversation_id = Column(
        Integer, ForeignKey("conversations.id"), nullable=False, index=True
    )
    role = Column(String, nullable=False)  # "human" | "ai" | "system"
    speaker_name = Column(String, nullable=True)  # e.g. character or player name
    content = Column(Text, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

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
            logger.warning(
                f"⚠️ Unknown message role '{self.role}' in message {self.id}, "
                "falling back to HumanMessage"
            )
            cls = HumanMessage

        kwargs: dict = {"content": self.content}
        if self.speaker_name:
            kwargs["name"] = self.speaker_name
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
    player_id = Column(
        Integer, ForeignKey("players.id"), nullable=True, index=True
    )
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

    # --- relationships ---------------------------------------------------

    player = relationship("Player", lazy="selectin")

    characters = relationship(
        "Character",
        secondary=conversation_characters,
        lazy="selectin",
    )

    messages = relationship(
        "Message",
        back_populates="conversation",
        order_by="Message.created_at",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

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

    def add_message(
        self,
        role: str,
        content: str,
        speaker_name: str | None = None,
    ) -> "Message":
        """💬 Append a new message to this conversation.

        Args:
            role: One of ``"human"``, ``"ai"``, or ``"system"``.
            content: The message body.
            speaker_name: Optional display name (character / player).

        Returns:
            The newly created Message instance.
        """
        with session.begin():
            msg = Message(role=role, content=content, speaker_name=speaker_name)
            self.messages.append(msg)
            session.add(msg)
            session.add(self)
            session.flush()
        logger.info(
            f"💬 [{role}] message added to conversation {self.id} "
            f"(speaker={speaker_name})"
        )
        return msg

    # ------------------------------------------------------------------
    # AgentSwarmState conversion
    # ------------------------------------------------------------------

    def to_agent_swarm_state(self) -> dict[str, list[AnyMessage]]:
        """🐝 Convert this conversation into an AgentSwarmState-compatible dict.

        Returns a dict with a single ``messages`` key whose value is
        a list of langchain message objects, ready to be passed as
        input to a compiled agent-swarm graph::

            state = conversation.to_agent_swarm_state()
            result = swarm.invoke(state, config={"configurable": {"thread_id": "..."}})
        """
        return {
            "messages": [msg.to_langchain_message() for msg in self.messages]
        }


    @classmethod
    def create(cls, player: Player, characters: list[Character]) -> "Conversation":
        """🎭 Create a new conversation between a player and one or more characters."""
        with session.begin():
            conversation = cls(player=player)
            for character in characters:
                conversation.add_character(character)
            conversation.title = f"{player.name} {', '.join([c.name for c in characters])}"
            session.add(conversation)
            session.flush()
        return conversation

    def __repr__(self) -> str:
        return (
            f"<Conversation(id={self.id}, title='{self.title}', "
            f"characters={len(self.characters)}, messages={len(self.messages)})>"
        )
