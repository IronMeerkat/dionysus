"""Custom Graphiti entity and edge types for the TTRPG domain.

Graphiti extracts these typed entities and relationships from conversation
episodes, building a temporally-aware knowledge graph.  Temporal edge
invalidation means "Orion is in the Zenith Chamber" gets superseded when a
later episode says "Orion is aboard the warship" -- no manual bookkeeping.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Entity types
# ---------------------------------------------------------------------------

class Character(BaseModel):
    """A named individual -- PC, NPC, or historical figure."""

    race: Optional[str] = Field(None, description="Race or species (e.g. High Elf, Human, Goblin, Feline Demihuman)")
    character_class: Optional[str] = Field(None, description="Class or role (e.g. Dynamic Weaver, Legionary, Netrunner)")
    alignment: Optional[str] = Field(None, description="Moral alignment or ethos")
    status: Optional[str] = Field(None, description="Current status (e.g. alive, dead, missing, augmented)")
    title: Optional[str] = Field(None, description="Title or epithet (e.g. CEO, Grand Chancellor, Patriarch)")


class Location(BaseModel):
    """A place -- city, district, building, landmark, or geographic feature."""

    location_type: Optional[str] = Field(None, description="Category (e.g. city, district, building, landmark, region)")
    parent_location: Optional[str] = Field(None, description="Containing location (e.g. 'Arclight' for a district within it)")
    terrain_type: Optional[str] = Field(None, description="Terrain or environment (e.g. urban, underground, industrial, arcology)")
    danger_level: Optional[str] = Field(None, description="Relative danger (e.g. safe, moderate, deadly)")


class Organization(BaseModel):
    """A group, corporation, military unit, noble house, or government body."""

    org_type: Optional[str] = Field(None, description="Kind of organization (e.g. megacorporation, noble house, military, government body, university, PMC)")
    industry: Optional[str] = Field(None, description="Primary industry or function (e.g. finance, defense manufacturing, mining, espionage)")
    parent_org: Optional[str] = Field(None, description="Parent organization if a subsidiary (e.g. 'Nightriver Holdings')")
    influence: Optional[str] = Field(None, description="Scope of influence (e.g. local, national, global)")


class Nation(BaseModel):
    """A sovereign political state or empire."""

    government_type: Optional[str] = Field(None, description="Form of government (e.g. republic, constitutional monarchy, theocracy)")
    dominant_race: Optional[str] = Field(None, description="Primary racial group in power")
    description: Optional[str] = Field(None, description="Brief summary of the nation's character")


class Race(BaseModel):
    """A sapient species or demihuman type."""

    legal_status: Optional[str] = Field(None, description="Legal classification (e.g. Sapient, Non-Sapient)")
    racial_category: Optional[str] = Field(None, description="Broader group (e.g. Elf subtype, Dwarf subtype, Demihuman)")
    notable_traits: Optional[str] = Field(None, description="Key racial traits or stereotypes in this setting")


class Concept(BaseModel):
    """A world mechanic, magic system element, technology, or societal structure."""

    concept_type: Optional[str] = Field(None, description="Category (e.g. magic system, technology, social structure, political concept)")
    domain: Optional[str] = Field(None, description="Related domain (e.g. Aether, Magitech, Kratian Society)")


class Creature(BaseModel):
    """A beast, monster, construct, or engineered organism."""

    creature_type: Optional[str] = Field(None, description="Origin (e.g. natural, magically-engineered, magitech construct, bio-weapon)")
    threat_level: Optional[str] = Field(None, description="Danger posed (e.g. low, moderate, extreme, apex)")


class Item(BaseModel):
    """A notable object, weapon, or artifact."""

    item_type: Optional[str] = Field(None, description="Category (e.g. weapon, armor, potion, artifact, cybernetic)")
    rarity: Optional[str] = Field(None, description="Rarity tier (e.g. common, rare, legendary)")
    magical: Optional[bool] = Field(None, description="Whether the item is magical or magitech")


class Event(BaseModel):
    """A significant occurrence -- historical, political, or in-play."""

    event_type: Optional[str] = Field(None, description="Category (e.g. battle, political shift, founding, betrayal, discovery)")
    significance: Optional[str] = Field(None, description="Impact level (e.g. minor, major, world-altering)")
    occurred_at: Optional[datetime] = Field(None, description="When the event took place in-world")


# ---------------------------------------------------------------------------
# Edge types
# ---------------------------------------------------------------------------

class Relationship(BaseModel):
    """A social or personal bond between characters."""

    relationship_type: Optional[str] = Field(None, description="Nature of the bond (e.g. ally, enemy, family, rival, mentor, employer)")
    sentiment: Optional[str] = Field(None, description="Current feeling (e.g. friendly, hostile, neutral, fearful)")


class Possession(BaseModel):
    """A character owns, wields, or carries an item."""

    acquisition_method: Optional[str] = Field(None, description="How it was obtained (e.g. looted, purchased, gifted, crafted)")
    equipped: Optional[bool] = Field(None, description="Whether the item is actively equipped or just carried")


class Membership(BaseModel):
    """A character belongs to an organization, faction, or nation."""

    rank: Optional[str] = Field(None, description="Rank or position within the group")
    standing: Optional[str] = Field(None, description="Current standing (e.g. honored, neutral, disgraced, founding member)")


class Presence(BaseModel):
    """An entity is at, controls, or is associated with a location."""

    presence_type: Optional[str] = Field(None, description="Nature of presence (e.g. visiting, residing, headquartered, ruling, imprisoned)")


class Participation(BaseModel):
    """An entity was involved in an event."""

    role: Optional[str] = Field(None, description="Role in the event (e.g. instigator, victim, witness, hero, perpetrator)")


class Hierarchy(BaseModel):
    """A parent-child or containment relationship between entities of the same kind."""

    hierarchy_type: Optional[str] = Field(None, description="Nature (e.g. subsidiary, subdivision, subdistrict, sub-race)")


class Governance(BaseModel):
    """A political or administrative control relationship."""

    governance_type: Optional[str] = Field(None, description="Nature (e.g. rules, regulates, legislates, enforces)")


# ---------------------------------------------------------------------------
# Registries -- passed to graphiti.add_episode()
# ---------------------------------------------------------------------------

ENTITY_TYPES: dict[str, type[BaseModel]] = {
    "Character": Character,
    "Location": Location,
    "Organization": Organization,
    "Nation": Nation,
    "Race": Race,
    "Concept": Concept,
    "Creature": Creature,
    "Item": Item,
    "Event": Event,
}

EDGE_TYPES: dict[str, type[BaseModel]] = {
    "Relationship": Relationship,
    "Possession": Possession,
    "Membership": Membership,
    "Presence": Presence,
    "Participation": Participation,
    "Hierarchy": Hierarchy,
    "Governance": Governance,
}

EDGE_TYPE_MAP: dict[tuple[str, str], list[str]] = {
    # Character edges
    ("Character", "Character"): ["Relationship"],
    ("Character", "Item"): ["Possession"],
    ("Character", "Location"): ["Presence"],
    ("Character", "Organization"): ["Membership"],
    ("Character", "Nation"): ["Membership"],
    ("Character", "Event"): ["Participation"],

    # Organization edges
    ("Organization", "Organization"): ["Hierarchy"],
    ("Organization", "Location"): ["Presence"],
    ("Organization", "Nation"): ["Membership"],
    ("Organization", "Event"): ["Participation"],

    # Nation edges
    ("Nation", "Location"): ["Governance", "Presence"],
    ("Nation", "Organization"): ["Governance"],
    ("Nation", "Event"): ["Participation"],

    # Race edges
    ("Race", "Race"): ["Hierarchy"],
    ("Race", "Nation"): ["Membership"],
    ("Race", "Location"): ["Presence"],

    # Location edges
    ("Location", "Location"): ["Hierarchy"],
    ("Location", "Event"): ["Participation"],

    # Creature edges
    ("Creature", "Location"): ["Presence"],
    ("Creature", "Organization"): ["Membership"],
    ("Creature", "Event"): ["Participation"],

    # Concept edges -- let these fall through to generic RELATES_TO
}
