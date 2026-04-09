"""🌍 Generalized Graphiti world and entry CRUD.

Worlds are identified by Graphiti ``group_id`` values.  Callers construct
group_ids for their domain (lore, character memories, etc.) and pass them
in directly.  Entry (episode) operations are fully group_id-agnostic.
"""

from datetime import datetime, timezone
from logging import getLogger

from graphiti_core.nodes import EpisodeType

from database.graphiti_types import EDGE_TYPE_MAP, EDGE_TYPES, ENTITY_TYPES
from database.graphiti_utils import GROUP_SEP, make_group_id, wipe_agent_memories
from database.init_graphiti import graphiti

logger = getLogger(__name__)

SEED_NAME = "__seed__"
SEED_SOURCE = "seed"

LORE_PREFIX = f"lore{GROUP_SEP}"


def lore_group_id(world_name: str) -> str:
    """Build the Graphiti group_id for a lore world."""
    return make_group_id("lore", world_name)


def name_from_group_id(group_id: str, prefix: str) -> str:
    """Extract the human-readable name by stripping *prefix* and un-escaping."""
    return group_id[len(prefix) :].replace("_", " ")


# ---------------------------------------------------------------------------
# World operations
# ---------------------------------------------------------------------------


async def list_worlds(prefix: str) -> list[dict[str, object]]:
    """Return all worlds whose group_id starts with *prefix*, with entry counts."""
    records, _, _ = await graphiti.driver.execute_query(
        """
        MATCH (e:Episodic)
        WHERE e.group_id STARTS WITH $prefix
        WITH e.group_id AS gid,
             count(e) AS total,
             sum(CASE WHEN e.source_description = $seed_src THEN 1 ELSE 0 END) AS seeds
        RETURN gid, total - seeds AS entry_count
        ORDER BY gid
        """,
        params={"prefix": prefix, "seed_src": SEED_SOURCE},
    )
    worlds: list[dict[str, object]] = []
    for record in records:
        gid = record["gid"]
        worlds.append({
            "name": name_from_group_id(gid, prefix),
            "entry_count": record["entry_count"],
        })
    return worlds


async def world_exists(group_id: str) -> bool:
    records, _, _ = await graphiti.driver.execute_query(
        "MATCH (e:Episodic {group_id: $gid}) RETURN e LIMIT 1",
        params={"gid": group_id},
    )
    return len(records) > 0


async def create_world_seed(group_id: str, display_name: str) -> dict[str, object]:
    """Create a lightweight seed episode so the world appears in listings."""
    result = await graphiti.add_episode(
        name=SEED_NAME,
        episode_body=f"World '{display_name}' created.",
        source=EpisodeType.text,
        source_description=SEED_SOURCE,
        reference_time=datetime.now(timezone.utc),
        group_id=group_id,
    )
    logger.info(f"🌍 Created seed episode for '{display_name}' (uuid={result.episode.uuid})")
    return {"name": display_name, "entry_count": 0}


async def delete_world(group_id: str) -> int:
    """Delete all episodes (including seed) for a world. Returns count deleted."""
    count = await wipe_agent_memories(group_id)
    logger.info(f"🗑️ Deleted world group_id={group_id!r} ({count} episodes)")
    return count


# ---------------------------------------------------------------------------
# Entry (episode) operations
# ---------------------------------------------------------------------------


async def list_entries(group_id: str) -> list[dict[str, object]]:
    """Return all non-seed episodes in a group, sorted by creation time."""
    episodes = await graphiti.retrieve_episodes(
        reference_time=datetime.now(timezone.utc),
        last_n=10_000,
        group_ids=[group_id],
    )

    entries: list[dict[str, object]] = []
    for ep in episodes:
        if ep.source_description == SEED_SOURCE:
            continue
        entries.append({
            "uuid": ep.uuid,
            "title": ep.name,
            "created_at": ep.created_at.isoformat(),
        })

    entries.sort(key=lambda e: str(e["created_at"]))
    return entries


async def get_entry(episode_uuid: str) -> dict[str, object] | None:
    """Fetch a single episode by UUID.  Returns ``group_id`` so callers can interpret it."""
    records, _, _ = await graphiti.driver.execute_query(
        """
        MATCH (e:Episodic {uuid: $uuid})
        RETURN e.uuid AS uuid, e.name AS title, e.content AS content,
               e.group_id AS group_id, e.created_at AS created_at
        """,
        params={"uuid": episode_uuid},
    )
    if not records:
        return None
    r = records[0]
    return {
        "uuid": r["uuid"],
        "title": r["title"],
        "content": r["content"],
        "group_id": r["group_id"],
        "created_at": r["created_at"].isoformat() if hasattr(r["created_at"], "isoformat") else str(r["created_at"]),
    }


async def create_entry(
    group_id: str,
    title: str,
    content: str,
    source_description: str = "manual",
) -> dict[str, object]:
    """Add an episode to a group.  Returns the created entry dict."""
    result = await graphiti.add_episode(
        name=title,
        episode_body=content,
        source=EpisodeType.text,
        source_description=source_description,
        reference_time=datetime.now(timezone.utc),
        group_id=group_id,
        entity_types=ENTITY_TYPES,
        edge_types=EDGE_TYPES,
        edge_type_map=EDGE_TYPE_MAP,
    )
    ep = result.episode
    logger.info(f"📜 Created entry '{title}' in group_id={group_id!r} (uuid={ep.uuid})")
    return {
        "uuid": ep.uuid,
        "title": ep.name,
        "content": ep.content,
        "group_id": group_id,
        "created_at": ep.created_at.isoformat(),
    }


async def update_entry(
    episode_uuid: str, title: str | None = None, content: str | None = None,
) -> dict[str, object] | None:
    """Update an entry by removing the old episode and creating a new one.

    Returns the new entry dict (with a new UUID), or None if the old episode
    was not found.
    """
    old = await get_entry(episode_uuid)
    if old is None:
        return None

    new_title = title if title is not None else str(old["title"])
    new_content = content if content is not None else str(old["content"])
    old_group_id = str(old["group_id"])

    await graphiti.remove_episode(episode_uuid)
    logger.info(f"✏️ Removed old episode {episode_uuid} for update")

    return await create_entry(old_group_id, new_title, new_content, source_description="update")


async def delete_entry(episode_uuid: str) -> bool:
    """Delete a single episode by UUID. Returns True if it existed."""
    entry = await get_entry(episode_uuid)
    if entry is None:
        return False
    await graphiti.remove_episode(episode_uuid)
    logger.info(f"🗑️ Deleted entry '{entry['title']}' (uuid={episode_uuid})")
    return True


# ---------------------------------------------------------------------------
# Entity (knowledge-graph node) operations
# ---------------------------------------------------------------------------


async def list_entities(group_id: str) -> list[dict[str, object]]:
    """Return all Entity nodes in a group, sorted by name."""
    records, _, _ = await graphiti.driver.execute_query(
        """
        MATCH (e:Entity)
        WHERE e.group_id = $gid
        RETURN e.uuid AS uuid, e.name AS name,
               e.created_at AS created_at, labels(e) AS labels
        ORDER BY e.name
        """,
        params={"gid": group_id},
    )
    entities: list[dict[str, object]] = []
    for r in records:
        raw_labels: list[str] = r["labels"]
        entity_type = next((l for l in raw_labels if l != "Entity"), "Entity")
        entities.append({
            "uuid": r["uuid"],
            "title": r["name"],
            "created_at": r["created_at"].isoformat() if hasattr(r["created_at"], "isoformat") else str(r["created_at"]),
            "kind": "entity",
            "entity_type": entity_type,
        })
    return entities


async def get_entity(entity_uuid: str) -> dict[str, object] | None:
    """Fetch a single Entity node by UUID, returning summary as content."""
    records, _, _ = await graphiti.driver.execute_query(
        """
        MATCH (e:Entity {uuid: $uuid})
        RETURN e.uuid AS uuid, e.name AS name, e.summary AS summary,
               e.group_id AS group_id, e.created_at AS created_at,
               labels(e) AS labels
        """,
        params={"uuid": entity_uuid},
    )
    if not records:
        return None
    r = records[0]
    raw_labels: list[str] = r["labels"]
    entity_type = next((l for l in raw_labels if l != "Entity"), "Entity")
    return {
        "uuid": r["uuid"],
        "title": r["name"],
        "content": r["summary"] or "",
        "group_id": r["group_id"],
        "created_at": r["created_at"].isoformat() if hasattr(r["created_at"], "isoformat") else str(r["created_at"]),
        "kind": "entity",
        "entity_type": entity_type,
    }


async def update_entity(
    entity_uuid: str, name: str | None = None, summary: str | None = None,
) -> dict[str, object] | None:
    """Update an Entity node's name and/or summary. Returns the updated dict or None."""
    old = await get_entity(entity_uuid)
    if old is None:
        return None

    new_name = name if name is not None else str(old["title"])
    new_summary = summary if summary is not None else str(old["content"])

    records, _, _ = await graphiti.driver.execute_query(
        """
        MATCH (e:Entity {uuid: $uuid})
        SET e.name = $name, e.summary = $summary
        RETURN e.uuid AS uuid, e.name AS name, e.summary AS summary,
               e.group_id AS group_id, e.created_at AS created_at,
               labels(e) AS labels
        """,
        params={"uuid": entity_uuid, "name": new_name, "summary": new_summary},
    )
    if not records:
        return None
    r = records[0]
    raw_labels: list[str] = r["labels"]
    entity_type = next((l for l in raw_labels if l != "Entity"), "Entity")
    logger.info(f"✏️ Updated entity '{new_name}' (uuid={entity_uuid})")
    return {
        "uuid": r["uuid"],
        "title": r["name"],
        "content": r["summary"] or "",
        "group_id": r["group_id"],
        "created_at": r["created_at"].isoformat() if hasattr(r["created_at"], "isoformat") else str(r["created_at"]),
        "kind": "entity",
        "entity_type": entity_type,
    }


async def delete_entity(entity_uuid: str) -> bool:
    """Delete an Entity node and its relationships. Returns True if it existed."""
    entity = await get_entity(entity_uuid)
    if entity is None:
        return False
    await graphiti.driver.execute_query(
        "MATCH (e:Entity {uuid: $uuid}) DETACH DELETE e",
        params={"uuid": entity_uuid},
    )
    logger.info(f"🗑️ Deleted entity '{entity['title']}' (uuid={entity_uuid})")
    return True
