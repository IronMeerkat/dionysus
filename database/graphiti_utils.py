import asyncio
from datetime import datetime, timezone
from logging import getLogger
from pathlib import Path

from langchain_core.messages import HumanMessage, AIMessage, AnyMessage

from graphiti_core.nodes import EpisodeType

from database.init_graphiti import graphiti
from database.graphiti_types import ENTITY_TYPES, EDGE_TYPES, EDGE_TYPE_MAP
from utils.llm_models import memory_filter
from utils.prompts import memory_significance_prompt

logger = getLogger(__name__)

NOTHING_MARKER = "NOTHING"

GROUP_SEP = "--"


def make_group_id(category: str, name: str) -> str:
    """Build a valid Graphiti group_id from category and name.

    Graphiti group_ids only allow alphanumeric chars, dashes, and underscores.
    """
    sanitized = name.replace(" ", "_").replace(":", "_")
    return f"{category}{GROUP_SEP}{sanitized}"


def make_memory_group_id(campaign_id: int, character_name: str) -> str:
    """Build a campaign-scoped memory group_id for a character."""
    return make_group_id("memories", f"campaign_{campaign_id}_{character_name}")


async def load_information(
    query: str,
    group_ids: list[str] | None = None,
    limit: int = 10,
    node_labels: list[str] | None = None,
    edge_types: list[str] | None = None,
) -> str:
    """Search the knowledge graph and return matching facts as a newline-joined string.

    Uses Graphiti's hybrid search (semantic + BM25 with RRF reranking).

    Optional filters narrow results to specific entity/edge types from
    ``graphiti_types.py`` (e.g. ``node_labels=["Character", "Location"]``).
    """
    logger.debug(f"🔍 Searching Graphiti graph with query: {query!r}, group_ids={group_ids}")

    search_filter = None
    if node_labels or edge_types:
        from graphiti_core.search.search_filters import SearchFilters
        search_filter = SearchFilters(node_labels=node_labels, edge_types=edge_types)

    edges = await graphiti.search(
        query=query,
        group_ids=group_ids,
        num_results=limit,
        search_filter=search_filter,
    )

    facts = [edge.fact for edge in edges if edge.fact]
    logger.debug(f"🔍 Found {len(facts)} facts")
    return "\n".join(facts)


async def insert_information(
    messages: list[AnyMessage],
    group_id: str,
    source_description: str = "conversation",
    perspective: str | None = None,
) -> None:
    """Ingest a conversation as a Graphiti episode.

    Formats LangChain messages into 'speaker: content' pairs and adds them
    as a single message-type episode.  When *perspective* is provided it is
    prepended to the episode body so the extraction LLM focuses on facts
    relevant to that point of view.
    """
    logger.info(f"💾 Inserting episode into Graphiti graph (group_id={group_id!r})")

    lines: list[str] = [f"{m.name}: {m.content}" for m in messages]

    if not lines:
        logger.warning("⚠️ No messages to insert, skipping")
        return

    episode_body = "\n".join(lines)
    name = f"conversation_{datetime.now(timezone.utc).isoformat()}"

    result = await graphiti.add_episode(
        name=name,
        episode_body=episode_body,
        source=EpisodeType.message,
        source_description=source_description,
        reference_time=datetime.now(timezone.utc),
        group_id=group_id,
        entity_types=ENTITY_TYPES,
        edge_types=EDGE_TYPES,
        edge_type_map=EDGE_TYPE_MAP,
        custom_extraction_instructions=perspective,
    )
    logger.debug(
        f"💾 Episode inserted: {len(result.nodes)} nodes, {len(result.edges)} edges"
    )


def _log_background_task_exception(task: asyncio.Task[None]) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.exception("🔥 Background memory task failed", exc_info=exc)


def fire_and_forget(coro: object) -> asyncio.Task[None]:
    """Schedule a coroutine as a background task with automatic error logging.

    Uses a blank ``contextvars.Context`` so LangChain/LangGraph streaming
    callbacks from the calling graph node are NOT inherited by the task.
    """
    import contextvars
    task = asyncio.create_task(coro, context=contextvars.Context())
    task.add_done_callback(_log_background_task_exception)
    return task


async def process_and_save_memory(
    messages: list[AnyMessage],
    group_id: str,
    source_description: str,
    perspective: str | None,
    character_name: str,
    character_description: str,
) -> None:
    """Filter conversation for meaningful memories, then persist to Graphiti.

    Calls the significance-filter LLM to decide whether anything worth
    remembering happened.  If yes, the distilled summary is ingested as
    a Graphiti episode.  If not, the save is skipped entirely.
    """
    lines = [f"{m.name}: {m.content}" for m in messages]
    if not lines:
        logger.warning("⚠️ No messages to evaluate for memory, skipping")
        return

    conversation_text = "\n".join(lines)

    prompt = await memory_significance_prompt.ainvoke({
        "name": character_name,
        "description": character_description,
        "conversation": conversation_text,
    })

    result = await memory_filter.ainvoke(prompt)
    extracted: str = result.content.strip()

    if not extracted or extracted.upper().startswith(NOTHING_MARKER):
        logger.info(f"🧹 {character_name}: nothing meaningful to remember, skipping save")
        return

    logger.info(f"🧠 {character_name}: meaningful memory extracted, saving to graph")

    name = f"memory_{character_name}_{datetime.now(timezone.utc).isoformat()}"

    await graphiti.add_episode(
        name=name,
        episode_body=extracted,
        source=EpisodeType.message,
        source_description=source_description,
        reference_time=datetime.now(timezone.utc),
        group_id=group_id,
        entity_types=ENTITY_TYPES,
        edge_types=EDGE_TYPES,
        edge_type_map=EDGE_TYPE_MAP,
        custom_extraction_instructions=perspective,
    )
    logger.debug(f"💾 {character_name}: memory episode persisted")


async def load_lorebook( lorebook: dict, world_name: str, *, batch_size: int = 5) -> int:
    """Load a SillyTavern-format lorebook dict into the Graphiti knowledge graph.

    Each lorebook entry becomes a separate ``text``-type episode so Graphiti
    can extract typed entities and relationships from the structured bracket-tag
    content.

    Args:
        lorebook: Already-parsed SillyTavern lorebook dictionary (the content
            of a ``worlds/<name>.json`` file).
        world_name: Identifier for the world (used in the group_id).
        batch_size: How many entries to ingest concurrently.  Keep modest to
            avoid overwhelming the LLM API with parallel extraction calls.

    Returns:
        Number of episodes ingested.
    """

    logger.info(f"📖 Loading lorebook (world={world_name!r})")

    entries = list(lorebook["entries"].values())
    if not entries:
        logger.warning("⚠️ No entries found in lorebook")
        return 0

    group_id = make_group_id("lore", world_name)
    now = datetime.now(timezone.utc)
    ingested = 0

    for batch_start in range(0, len(entries), batch_size):
        batch = entries[batch_start : batch_start + batch_size]
        tasks = []
        for entry in batch:
            content = entry["content"].strip()
            if not content:
                continue

            name = entry["comment"]
            tasks.append(
                graphiti.add_episode(
                    name=name,
                    episode_body=content,
                    source=EpisodeType.text,
                    source_description=f"lorebook:{world_name}",
                    reference_time=now,
                    group_id=group_id,
                    entity_types=ENTITY_TYPES,
                    edge_types=EDGE_TYPES,
                    edge_type_map=EDGE_TYPE_MAP,
                )
            )

        results = await asyncio.gather(*tasks, return_exceptions=True)
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                entry_name = batch[i]["comment"]
                logger.error(f"❌ Failed to ingest '{entry_name}': {result}")
            else:
                ingested += 1

        logger.info(
            f"📖 Batch {batch_start // batch_size + 1}: "
            f"ingested {sum(1 for r in results if not isinstance(r, Exception))}/{len(tasks)} entries"
        )

    logger.info(f"✅ Lorebook loading complete: {ingested}/{len(entries)} entries ingested")
    return ingested


async def wipe_campaign_memories(campaign_id: int) -> int:
    """Remove all Graphiti nodes whose group_id belongs to this campaign.

    Uses a single Cypher DETACH DELETE so we don't need to know individual
    character names up-front.

    Returns the number of nodes deleted.
    """
    prefix = f"memories{GROUP_SEP}campaign_{campaign_id}_"
    logger.info(f"🗑️ Wiping all Graphiti nodes with group_id prefix '{prefix}'")

    records, _, _ = await graphiti.driver.execute_query(
        "MATCH (n) WHERE n.group_id STARTS WITH $prefix DETACH DELETE n RETURN count(n) AS deleted",
        params={"prefix": prefix},
    )

    deleted: int = records[0]["deleted"] if records else 0
    logger.info(f"🗑️ Deleted {deleted} Graphiti nodes for campaign {campaign_id}")
    return deleted


async def wipe_agent_memories(group_id: str) -> int:
    """Remove all episodes for a given group_id.

    Returns the number of episodes deleted.
    """
    logger.info(f"🗑️ Wiping episodes for group_id={group_id!r}")

    episodes = await graphiti.retrieve_episodes(
        reference_time=datetime.now(timezone.utc),
        last_n=10_000,
        group_ids=[group_id],
    )

    for episode in episodes:
        await graphiti.remove_episode(episode.uuid)

    logger.info(f"🗑️ Deleted {len(episodes)} episodes for group_id={group_id!r}")
    return len(episodes)
