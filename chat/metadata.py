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


def effective_node(metadata: dict, path_from_namespace: list[str] | None = None) -> str | None:
    """Resolve node name from metadata (supports nested graphs via langgraph_path)."""
    inner_node = metadata.get("langgraph_node")
    path = path_from_namespace or metadata.get("langgraph_path")
    if inner_node and inner_node in NARRATOR_NODES:
        return inner_node
    return path[-1] if path else inner_node


def resolve_speaker(
    metadata: dict,
    graph_node_to_character_name: dict[str, str],
    path_from_namespace: list[str] | None = None,
) -> str | None:
    """Resolve character name from stream metadata. Innermost path element wins."""
    path = path_from_namespace or metadata.get("langgraph_path")
    if path:
        matching = [graph_node_to_character_name[e] for e in path if e in graph_node_to_character_name]
        if matching:
            return matching[-1]
    node = metadata.get("langgraph_node")
    if node and node in graph_node_to_character_name:
        return graph_node_to_character_name[node]
    raise ValueError(
        "Could not determine which character is speaking. Please try again.",
        metadata,
        graph_node_to_character_name,
        path_from_namespace,
    )


def path_from_namespace(namespace: tuple[str, ...]) -> list[str]:
    """Extract node names from namespace, e.g. ('character_1:uuid', 'planner:uuid') -> ['character_1', 'planner']."""
    return [
        name for part in namespace
        if not (name := part.split(":")[0] if ":" in part else part).startswith("__")
    ]
