import asyncio
import uuid
from typing import Annotated
import operator
from uuid import uuid4
from pydantic import BaseModel, Field
from langchain_core.messages import AnyMessage, HumanMessage
from langchain_xai import ChatXAI
from langgraph.graph import END, START, StateGraph
from logging import getLogger

from hephaestus.agent_architectures import create_daisy_chain, wrap_agent_return_delta

from database.graphiti_utils import insert_information, make_group_id
from database.models.conversation import Conversation
from utils.prompts import scene_change_prompt_template
from agents.nonplayer import spawn_npc

logger = getLogger(__name__)


class SceneChanged(BaseModel):
    scene_changed: bool = Field(default=False, description="true if there was a time skip, false otherwise")


scene_change_model = ChatXAI(model="grok-4-1-fast", temperature=0, max_tokens=128, max_retries=3
                            ).with_structured_output(SceneChanged, strict=True)

class DungeonMasterState(BaseModel):
    messages: Annotated[list[AnyMessage], operator.add]


def spawn_dungeon_master(conversation: Conversation, name: str = 'dungeon_master') -> StateGraph:

    player = conversation.player
    characters = conversation.characters

    npc_swarm = create_daisy_chain(*[spawn_npc(c, conversation) for c in characters], name="npc_swarm")

    
    # TODO add DM logic and nodes here


    async def persist_messages(state: DungeonMasterState) -> DungeonMasterState:

        for message in state.messages:
            if message.id is None:
                message.id = str(uuid4())

            if isinstance(message, HumanMessage):
                message.name = player.name

        conversation.message_buffer.extend(state.messages)

        for message in state.messages:
            conversation.add_message(message.type, message.content, message.name)

        ids = [msg.id for msg in conversation.message_buffer]
        dupes = len(ids) - len(set(ids))
        if dupes:
            logger.error(f"👯‍♀️ {dupes} duplicate message IDs detected")

        return {'messages': []}

    graph = StateGraph(DungeonMasterState)
    graph.add_node("npc_swarm", wrap_agent_return_delta(npc_swarm))
    graph.add_node("persist_messages", persist_messages, defer=True)
    graph.add_edge(START, "npc_swarm")
    graph.add_edge("npc_swarm", "persist_messages")
    graph.add_edge("persist_messages", END)

    return graph.compile(name=name)
