import asyncio
from typing import Annotated
import operator

from pydantic import BaseModel, Field
from langchain_core.messages import AnyMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_xai import ChatXAI
from langgraph.graph import END, START, StateGraph
from logging import getLogger

from hephaestus.agent_architectures import create_daisy_chain, wrap_agent_return_delta

from database.initialize_mem0 import memory
from database.models import Character as CharacterModel, Player as PlayerModel
from database.postgres_connection import session
from tools import tabletop
from utils.prompts import character_episodic_memory, scene_change_prompt_template
from agents.nonplayer import spawn_npc

logger = getLogger(__name__)


class SceneChanged(BaseModel):
    scene_changed: bool = Field(default=False, description="true if there was a time skip, false otherwise")


scene_change_model = ChatXAI(model="grok-4-1-fast", temperature=0, max_tokens=128, max_retries=3
                            ).with_structured_output(SceneChanged, strict=True)

class DungeonMasterState(BaseModel):
    messages: Annotated[list[AnyMessage], operator.add]


def spawn_dungeon_master(*characters: CharacterModel, player: PlayerModel, name: str = 'dungeon_master') -> StateGraph:

    # TODO make an actual DM agent

    tabletop.player = player
    tabletop.characters = characters

    npc_swarm = create_daisy_chain(*[spawn_npc(c) for c in characters], name="npc_swarm")

    
    # TODO add DM logic and nodes here


    async def update_tabletop_messages(state: DungeonMasterState) -> DungeonMasterState:

        prompt = await scene_change_prompt_template.ainvoke({"messages": state.messages})
        scene_changed = await scene_change_model.ainvoke(prompt)

        logger.info(f"🔄 Scene changed: {scene_changed}")

        if scene_changed is None or scene_changed.scene_changed is None:
            logger.error("🔄 scene_changed returned None or NoneType, presuming no scene change")
            scene_change = False
        else:
            scene_change = scene_changed.scene_changed


        if scene_change and tabletop.messages:
            logger.info("🔄 Scene changed! Updating memories...")   
            tasks = [
                asyncio.create_task(
                    memory.add(
                        messages=tabletop.messages,
                        user_id="user",
                        metadata={"memory_category": "memories", "agent": character.name, "world": tabletop.lore_world},
                        prompt=character_episodic_memory.compile(name=character.name)
                    )
                )
                for character in tabletop.characters
            ]
            await asyncio.gather(*tasks)
            tabletop.messages = state.messages
        
        else:
            logger.debug("🔄 No scene change detected, continuing...")
            tabletop.messages.extend(state.messages)


        return {'messages': []}

    graph = StateGraph(DungeonMasterState)
    graph.add_node("npc_swarm", wrap_agent_return_delta(npc_swarm))
    graph.add_node("update_tabletop_messages", update_tabletop_messages, defer=True)
    graph.add_edge(START, "npc_swarm")
    graph.add_edge("npc_swarm", "update_tabletop_messages")
    graph.add_edge("update_tabletop_messages", END)

    return graph.compile(name=name)


