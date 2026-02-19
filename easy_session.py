from hephaestus.logging import init_logger
init_logger()
from database.postgres_connection import session
from database.models import Player, Character
from hephaestus.langfuse_handler import langfuse_callback_handler

from agents.dungeon_master import spawn_dungeon_master
from langchain_core.messages import HumanMessage


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