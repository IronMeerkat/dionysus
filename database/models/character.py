from datetime import datetime, timezone
from logging import getLogger

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, select
from sqlalchemy.orm import relationship

from database.postgres_connection import Base

logger = getLogger(__name__)


class CharacterDescription(Base):
    """📜 A single versioned description for a character.

    Each row represents one version of a character's description prompt.
    Versions are auto-incremented per character, and the latest version
    is always the active description.
    """

    __tablename__ = "character_descriptions"

    id = Column(Integer, primary_key=True)
    character_id = Column(Integer, ForeignKey("characters.id"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    body = Column(Text, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    character = relationship("Character", back_populates="description_versions")

    def __repr__(self) -> str:
        return (
            f"<CharacterDescription(character_id={self.character_id}, "
            f"v{self.version}, created={self.created_at})>"
        )


class Character(Base):
    """🎭 A playable or non-player character with versioned descriptions."""

    __tablename__ = "characters"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, index=True, unique=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    description_versions = relationship(
        "CharacterDescription",
        back_populates="character",
        order_by="CharacterDescription.version",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    # ------------------------------------------------------------------
    # Description helpers
    # ------------------------------------------------------------------

    @property
    def description(self) -> str | None:
        """Return the latest (current) description, or None if no versions exist."""
        if not self.description_versions:
            return None
        return self.description_versions[-1].body

    @property
    def description_version(self) -> int | None:
        """Return the current description's version number."""
        if not self.description_versions:
            return None
        return self.description_versions[-1].version

    def add_description(self, body: str) -> "CharacterDescription":
        """📝 Append a new description version.

        The version number is automatically set to the next value.

        Args:
            body: The new description text.

        Returns:
            The newly created CharacterDescription instance.
        """
        next_version = (self.description_version or 0) + 1
        desc = CharacterDescription(
            version=next_version,
            body=body,
        )
        self.description_versions.append(desc)
        logger.info(
            f"📝 Character '{self.name}' description updated to v{next_version}"
        )
        return desc

    def get_description_at_version(self, version: int) -> str | None:
        """🔍 Retrieve the description body for a specific version.

        Args:
            version: The version number to look up.

        Returns:
            The description text, or None if the version doesn't exist.
        """
        for desc in self.description_versions:
            if desc.version == version:
                return desc.body
        logger.warning(
            f"⚠️ Version {version} not found for character '{self.name}'"
        )
        return None

    @property
    def description_history(self) -> list["CharacterDescription"]:
        """📚 Return the full ordered history of descriptions."""
        return list(self.description_versions)

    def __repr__(self) -> str:
        return f"<Character(id={self.id}, name='{self.name}', desc_v={self.description_version})>"


# ======================================================================
# Player
# ======================================================================


class PlayerDescription(Base):
    """📜 A single versioned description for a player.

    Each row represents one version of a player's description prompt.
    Versions are auto-incremented per player, and the latest version
    is always the active description.
    """

    __tablename__ = "player_descriptions"

    id = Column(Integer, primary_key=True)
    player_id = Column(Integer, ForeignKey("players.id"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    body = Column(Text, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    player = relationship("Player", back_populates="description_versions")

    def __repr__(self) -> str:
        return (
            f"<PlayerDescription(player_id={self.player_id}, "
            f"v{self.version}, created={self.created_at})>"
        )


class Player(Base):
    """🎮 The human player with versioned descriptions.

    Follows the same version-controlled description pattern as Character,
    keeping a full history of description revisions.
    """

    __tablename__ = "players"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, index=True, unique=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    description_versions = relationship(
        "PlayerDescription",
        back_populates="player",
        order_by="PlayerDescription.version",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    # ------------------------------------------------------------------
    # Description helpers
    # ------------------------------------------------------------------

    @property
    def description(self) -> str | None:
        """Return the latest (current) description, or None if no versions exist."""
        if not self.description_versions:
            return None
        return self.description_versions[-1].body

    @property
    def description_version(self) -> int | None:
        """Return the current description's version number."""
        if not self.description_versions:
            return None
        return self.description_versions[-1].version

    def add_description(self, body: str) -> "PlayerDescription":
        """📝 Append a new description version.

        The version number is automatically set to the next value.

        Args:
            body: The new description text.

        Returns:
            The newly created PlayerDescription instance.
        """
        next_version = (self.description_version or 0) + 1
        desc = PlayerDescription(
            version=next_version,
            body=body,
        )
        self.description_versions.append(desc)
        logger.info(
            f"📝 Player '{self.name}' description updated to v{next_version}"
        )
        return desc

    def get_description_at_version(self, version: int) -> str | None:
        """🔍 Retrieve the description body for a specific version.

        Args:
            version: The version number to look up.

        Returns:
            The description text, or None if the version doesn't exist.
        """
        for desc in self.description_versions:
            if desc.version == version:
                return desc.body
        logger.warning(
            f"⚠️ Version {version} not found for player '{self.name}'"
        )
        return None

    @property
    def description_history(self) -> list["PlayerDescription"]:
        """📚 Return the full ordered history of descriptions."""
        return list(self.description_versions)

    def __repr__(self) -> str:
        return f"<Player(id={self.id}, name='{self.name}', desc_v={self.description_version})>"
