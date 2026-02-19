from typing import Annotated
import operator

from pydantic import BaseModel
from langchain_core.messages import AnyMessage
from langgraph.graph import END, START, StateGraph

from hephaestus.agent_architectures import create_daisy_chain, wrap_agent_return_delta

from database.models import Character as CharacterModel, Player as PlayerModel
from database.postgres_connection import session
from tools import tabletop

from agents.nonplayer import spawn_npc


class DungeonMasterState(BaseModel):
    messages: Annotated[list[AnyMessage], operator.add]


def spawn_dungeon_master(*characters: CharacterModel, player: PlayerModel, name: str = 'dungeon_master') -> StateGraph:

    # TODO make an actual DM agent

    tabletop.player = player
    tabletop.characters = characters

    npc_swarm = create_daisy_chain(*[spawn_npc(c) for c in characters], name="npc_swarm")

    
    # TODO add DM logic and nodes here


    async def update_tabletop_messages(state: DungeonMasterState) -> DungeonMasterState:
        tabletop.messages.extend(state.messages)
        return {'messages': []}

    graph = StateGraph(DungeonMasterState)
    graph.add_node("npc_swarm", wrap_agent_return_delta(npc_swarm))
    graph.add_node("update_tabletop_messages", update_tabletop_messages, defer=True)
    graph.add_edge(START, "npc_swarm")
    graph.add_edge("npc_swarm", "update_tabletop_messages")
    graph.add_edge("update_tabletop_messages", END)

    return graph.compile(name=name)


