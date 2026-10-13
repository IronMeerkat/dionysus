"""The DM supervisor package."""
from agents.dungeon_master.schemas import (
    NARRATOR_NAME,
    Adjudication,
    DMPlan,
    NPCIntroduction,
)

__all__ = [
    "Adjudication",
    "DMPlan",
    "NARRATOR_NAME",
    "NPCIntroduction",
    "spawn_dungeon_master",
]


def __getattr__(name: str):
    if name == "spawn_dungeon_master":
        from agents.dungeon_master.graph import spawn_dungeon_master

        return spawn_dungeon_master
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
