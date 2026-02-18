from database.postgres_connection import session
from database.models import Player, Character
from hephaestus.agent_architectures import create_daisy_chain
from hephaestus.langfuse_handler import langfuse_callback_handler

from agents.nonplayer import spawn_npc
from langchain_core.messages import HumanMessage


class EasySession:

    def __init__(self, player: int, characters: list[int]):
        self.player = session.query(Player).filter(Player.id == player).first()
        self.characters = session.query(Character).filter(Character.id.in_(characters)).all()
        self.daisy_chain = create_daisy_chain(*[spawn_npc(c, self.player) for c in self.characters], name="npc_swarm")
        self._messages = []

    async def send_message(self, message: str) -> list[str]:
        resp = await self.daisy_chain.ainvoke(
            {"messages": [*self._messages, HumanMessage(content=message)]},
            config={"callbacks": [langfuse_callback_handler]},
        )
        self._messages = resp['messages']

    @property
    def messages(self):
        return [m.content for m in self._messages]