"""🌍 Neo4j-backed lore world and entry CRUD.

Worlds are identified by Graphiti ``group_id`` (format ``lore--<name>``).
Entries are Graphiti episodes within a world's group_id.
"""

from datetime import datetime, timezone
from logging import getLogger

from graphiti_core.nodes import EpisodeType

from database.graphiti_types import EDGE_TYPE_MAP, EDGE_TYPES, ENTITY_TYPES
from database.graphiti_utils import GROUP_SEP, make_group_id, wipe_agent_memories
from database.init_graphiti import graphiti

logger = getLogger(__name__)

LORE_PREFIX = f"lore{GROUP_SEP}"
SEED_NAME = "__seed__"
SEED_SOURCE = "seed"


def _world_name_from_group_id(group_id: str) -> str:
    """Extract the human-readable world name from a lore group_id."""
    return group_id[len(LORE_PREFIX):].replace("_", " ")


def _lore_group_id(world_name: str) -> str:
    return make_group_id("lore", world_name)


# ---------------------------------------------------------------------------
# World operations
# ---------------------------------------------------------------------------


async def list_lore_worlds() -> list[dict[str, object]]:
    """Return all lore worlds with entry counts (excluding seed episodes)."""
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
        params={"prefix": LORE_PREFIX, "seed_src": SEED_SOURCE},
    )
    worlds: list[dict[str, object]] = []
    for record in records:
        gid = record["gid"]
        worlds.append({
            "name": _world_name_from_group_id(gid),
            "entry_count": record["entry_count"],
        })
    return worlds


async def world_exists(world_name: str) -> bool:
    group_id = _lore_group_id(world_name)
    records, _, _ = await graphiti.driver.execute_query(
        "MATCH (e:Episodic {group_id: $gid}) RETURN e LIMIT 1",
        params={"gid": group_id},
    )
    return len(records) > 0


async def create_world_seed(world_name: str) -> dict[str, object]:
    """Create a lightweight seed episode so the world appears in listings."""
    group_id = _lore_group_id(world_name)
    result = await graphiti.add_episode(
        name=SEED_NAME,
        episode_body=f"World '{world_name}' created.",
        source=EpisodeType.text,
        source_description=SEED_SOURCE,
        reference_time=datetime.now(timezone.utc),
        group_id=group_id,
    )
    logger.info(f"🌍 Created seed episode for world '{world_name}' (uuid={result.episode.uuid})")
    return {"name": world_name, "entry_count": 0}


async def delete_world(world_name: str) -> int:
    """Delete all episodes (including seed) for a lore world. Returns count deleted."""
    group_id = _lore_group_id(world_name)
    count = await wipe_agent_memories(group_id)
    logger.info(f"🗑️ Deleted world '{world_name}' ({count} episodes)")
    return count


# ---------------------------------------------------------------------------
# Entry (episode) operations
# ---------------------------------------------------------------------------


async def list_world_entries(world_name: str) -> list[dict[str, object]]:
    """Return all non-seed episodes in a world, newest first."""
    group_id = _lore_group_id(world_name)
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
    """Fetch a single episode by UUID."""
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
    gid = r["group_id"]
    return {
        "uuid": r["uuid"],
        "title": r["title"],
        "content": r["content"],
        "world_name": _world_name_from_group_id(gid) if gid.startswith(LORE_PREFIX) else gid,
        "created_at": r["created_at"].isoformat() if hasattr(r["created_at"], "isoformat") else str(r["created_at"]),
    }


async def create_entry(
    world_name: str, title: str, content: str,
) -> dict[str, object]:
    """Add a lore episode to a world. Returns the created entry dict."""
    group_id = _lore_group_id(world_name)
    result = await graphiti.add_episode(
        name=title,
        episode_body=content,
        source=EpisodeType.text,
        source_description=f"lore_creator:{world_name}",
        reference_time=datetime.now(timezone.utc),
        group_id=group_id,
        entity_types=ENTITY_TYPES,
        edge_types=EDGE_TYPES,
        edge_type_map=EDGE_TYPE_MAP,
    )
    ep = result.episode
    logger.info(f"📜 Created entry '{title}' in world '{world_name}' (uuid={ep.uuid})")
    return {
        "uuid": ep.uuid,
        "title": ep.name,
        "content": ep.content,
        "world_name": world_name,
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
    world_name = str(old["world_name"])

    await graphiti.remove_episode(episode_uuid)
    logger.info(f"✏️ Removed old episode {episode_uuid} for update")

    return await create_entry(world_name, new_title, new_content)


async def delete_entry(episode_uuid: str) -> bool:
    """Delete a single episode by UUID. Returns True if it existed."""
    entry = await get_entry(episode_uuid)
    if entry is None:
        return False
    await graphiti.remove_episode(episode_uuid)
    logger.info(f"🗑️ Deleted entry '{entry['title']}' (uuid={episode_uuid})")
    return True
