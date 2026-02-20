"""
🔍 Metadata resolution for LangGraph stream output.

Resolves node names and character attribution from stream metadata,
supporting nested graphs via langgraph_path.
"""
from __future__ import annotations

NODE_PLANNER = "planner"
NODE_USE_TOOLS = "use_tools"
NODE_NARRATOR = "npc_narrator"
NARRATOR_NODES = frozenset({NODE_PLANNER, NODE_USE_TOOLS, NODE_NARRATOR})

def resolve_speaker(character_list: list[str], path: list[str]) -> str:
    """Resolve character name from stream metadata. Innermost path element wins."""
    if len(character_list) == 1:
        return character_list[0]
    
    matching = [c for c in path if c in character_list]
    return matching[-1]


def path_from_namespace(namespace: tuple[str, ...]) -> list[str]:
    """Extract node names from namespace, e.g. ('character_1:uuid', 'planner:uuid') -> ['character_1', 'planner']."""
    return [
        name for part in namespace
        if not (name := part.split(":")[0] if ":" in part else part).startswith("__")
    ]
