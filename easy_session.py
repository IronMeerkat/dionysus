import asyncio
from logging import getLogger

from hephaestus.logging import init_logger
init_logger()
from database.initialize_mem0 import memory
from database.postgres_connection import session
from database.models import Player, Character
from hephaestus.langfuse_handler import langfuse_callback_handler

from agents.dungeon_master import spawn_dungeon_master
from langchain_core.messages import HumanMessage

logger = getLogger(__name__)


async def wipe_agent_memories(agent_name: str= None) -> int:
    """Deletes all memories with metadata `memory_category=memories` for the given agent name.

    Returns the number of memories deleted.
    """
    filters = [{"memory_category": "memories"}]
    if agent_name:
        filters.append({"agent": agent_name})

    all_memories = await memory.get_all(
        user_id="user",
        filters={"AND": filters},
        limit=10_000,
    )

    results = all_memories.get("results", [])
    if not results:
        logger.info(f"🗑️ No memories found for agent '{agent_name}'")
        return 0

    logger.info(f"🗑️ Deleting {len(results)} memories for agent '{agent_name}'...")
    tasks = [asyncio.create_task(memory.delete(m["id"])) for m in results]
    await asyncio.gather(*tasks)
    logger.info(f"✅ Successfully wiped {len(results)} memories for agent '{agent_name}'")
    return len(results)


class EasySession:

    def __init__(self, player: int, characters: list[int]):
        self.player = session.query(Player).filter(Player.id == player).first()
        self.characters = session.query(Character).filter(Character.id.in_(characters)).all()
        self.dungeon_master = spawn_dungeon_master(*self.characters, player=self.player)
        self._messages = []

    async def send_message(self, message: str) -> list[str]:
        resp = await self.dungeon_master.ainvoke(
            {"messages": [HumanMessage(content=message)]},
            config={"callbacks": [langfuse_callback_handler]},
        )
        self._messages = resp['messages']

    @property
    def messages(self):
        return [m.content for m in self._messages]