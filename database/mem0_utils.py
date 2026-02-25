from langchain_core.messages import HumanMessage, AIMessage, AnyMessage
from logging import getLogger
from database.initialize_mem0 import memory


logger = getLogger(__name__)

async def load_information(query: str, metadata_filters: dict[str, str], rerank_threshold: float = None, limit: int = None) -> str:
    """Loads information from the database.

    Returns the information loaded.
    """
    logger.debug(f"Loading information from the mem0 database")
    results = (await memory.search(
        query=query,
        user_id="user",
        filters=metadata_filters,
        rerank=True,
    ))['results']

    if rerank_threshold is not None:
        results = [m for m in results if m['rerank_score'] > rerank_threshold]
    if limit is not None:
        limit = min(limit, len(results))
        results = results[:limit]

    return '\n'.join([m['memory'] for m in results])


async def insert_information(messages: list[AnyMessage], metadata_filters: dict[str, str], prompt: str) -> None:
    """Inserts information into the database.

    Returns the information inserted.
    """
    logger.info(f"💾 Inserting information into the mem0 database")

    for message in messages:
        if isinstance(message, HumanMessage):
            message.role = "user"
        elif isinstance(message, AIMessage):
            message.role = "assistant"

    results = await memory.add(
        messages=[m.model_dump() for m in messages],
        user_id="user",
        metadata=metadata_filters,
        prompt=prompt,
    )
    logger.debug(f"💾 Inserted {len(results)} memories into the mem0 database")

async def wipe_agent_memories(agent_name: str) -> int:
    """Deletes all memories with metadata `memory_subcategory=memories` for the given agent name.

    Returns the number of memories deleted.
    """
    all_memories = await memory.get_all(
        user_id="user",
        filters={"AND": [{"memory_subcategory": "memories"}, {"agent": agent_name}]},
        limit=10_000,
    )
    return len(all_memories)

