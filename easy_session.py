from logging import getLogger

from hephaestus.logging import init_logger
init_logger()
from database.knowledge import wipe_character_memories
from database.postgres_connection import session
from database.models import Character, Conversation
from hephaestus.langfuse_handler import langfuse_callback_handler

from agents.dungeon_master import spawn_dungeon_master
from langchain_core.messages import HumanMessage

logger = getLogger(__name__)


async def wipe_agent_memories(campaign_id: int, agent_name: str) -> int:
    """Deletes all memories of the given character within a campaign.

    Returns the number of rows deleted.
    """
    character = session.query(Character).filter(Character.name == agent_name).first()
    if character is None:
        logger.warning(f"⚠️ No character named '{agent_name}', nothing to wipe")
        return 0
    return wipe_character_memories(campaign_id, character.id)


class EasySession:

    def __init__(self, player: int, characters: list[int], campaign_id: int):
        player_obj = session.query(Character).filter(Character.id == player).first()
        character_objs = session.query(Character).filter(Character.id.in_(characters)).all()

        self.conversation = Conversation.create(
            player=player_obj,
            characters=character_objs,
            campaign_id=campaign_id,
        )
        self.graph = spawn_dungeon_master(self.conversation)
        self._messages: list = []

    async def send_message(self, message: str) -> list[str]:
        resp = await self.graph.ainvoke(
            {"messages": [HumanMessage(content=message)]},
            config={"callbacks": [langfuse_callback_handler]},
        )
        self._messages = resp['messages']

    @property
    def messages(self):
        return [m.content for m in self._messages]
