from logging import getLogger

from hephaestus.logging import init_logger
init_logger()
from database.graphiti_utils import wipe_agent_memories as _graphiti_wipe, make_group_id
from database.postgres_connection import session
from database.models import Player, Character, Conversation
from hephaestus.langfuse_handler import langfuse_callback_handler
from hephaestus.settings import settings
from utils.prompts import placeholder_location, placeholder_scenario

from agents.dungeon_master import spawn_dungeon_master
from langchain_core.messages import HumanMessage

logger = getLogger(__name__)


async def wipe_agent_memories(agent_name: str) -> int:
    """Deletes all Graphiti episodes for the given agent's memory group.

    Returns the number of episodes deleted.
    """
    group_id = make_group_id("memories", agent_name)
    return await _graphiti_wipe(group_id)


class EasySession:

    def __init__(self, player: int, characters: list[int]):
        player_obj = session.query(Player).filter(Player.id == player).first()
        character_objs = session.query(Character).filter(Character.id.in_(characters)).all()

        self.conversation = Conversation.create(
            player=player_obj,
            characters=character_objs,
            location=placeholder_location,
            story_background=placeholder_scenario,
            lore_world=settings.PLACEHOLDER_LORE_WORLD,
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
