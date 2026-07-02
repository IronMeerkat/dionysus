"""The DM supervisor package: a world-runtime, referee, and drama director.

Public surface mirrors the old single-module ``agents.dungeon_master``:
``spawn_dungeon_master``, ``NARRATOR_NAME``, and the directive/plan schemas.
"""
from agents.dungeon_master.graph import spawn_dungeon_master
from agents.dungeon_master.schemas import (
    NARRATOR_NAME,
    Adjudication,
    DMPlan,
    DungeonMasterState,
    IntentReading,
    NPCDirective,
    NPCIntroduction,
)

__all__ = [
    "Adjudication",
    "DMPlan",
    "DungeonMasterState",
    "IntentReading",
    "NARRATOR_NAME",
    "NPCDirective",
    "NPCIntroduction",
    "spawn_dungeon_master",
]
