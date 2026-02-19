from logging import getLogger
from typing import Callable, Dict, Iterable, Optional, Annotated, List
import operator
from uuid import uuid4


from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, AnyMessage, ToolMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_xai import ChatXAI
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from hephaestus.langfuse_handler import langfuse, langfuse_callback_handler
from database.initialize_mem0 import memory
from database.models import Character as CharacterModel, Player as PlayerModel
from tools.dice import roll_d20, roll_d10, roll_d6
from tools import tabletop
from utils.prompts import plan_prompt_template, tool_prompt_template, narrator_prompt_template

logger = getLogger(__name__)

model = ChatXAI(
    model="grok-4-1-fast-reasoning",
    temperature=0.9,
    callbacks=[langfuse_callback_handler],
    max_retries=3,
)



tools = [roll_d20, roll_d10, roll_d6]
tools_by_name = {tool.name: tool for tool in tools}

def spawn_npc(character: CharacterModel) -> StateGraph:

    other_characters = [f"**{c.name}**:\n{c.description}" 
                        for c in tabletop.characters 
                        if c.id != character.id]

    # other_character_names = [c.name for c in tabletop.characters if c.id != character.id]
    # other_character_names = ', '.join(other_character_names)

    other_characters = '\n\n\n'.join(other_characters)


    class NPCState(BaseModel):
        messages: Annotated[list[AnyMessage], operator.add]
        thoughts: str = ''
        lore: str = ''

        @property
        def combined_dump(self) -> dict:
            return {
                'name': character.name,
                'description': character.description,
                'other_characters': other_characters,
                'player': tabletop.player.description,
                'location': tabletop.location,
                'messages': [*tabletop.messages, *self.messages],
                **self.model_dump(exclude={'messages'}),
            }

    async def memory_loader(state: NPCState) -> NPCState:
        last_human_message = next(m for m in reversed(state.messages) if isinstance(m, HumanMessage))
        lore = (await memory.search(
            query=last_human_message.content,
            user_id="user",
            metadata_filters={"OR": [{"memory_category": "lore"}]},
            rerank=True,
        ))['results']

        lore = [m for m in lore if m['rerank_score'] > 0.6]
        limit = min(20, len(lore))
        lore = lore[:limit]

        return {'lore': '\n'.join([m['memory'] for m in lore]), 'messages': []}

    async def planner(state: NPCState) -> NPCState:

        prompt = await plan_prompt_template.ainvoke(state.combined_dump)
        logger.debug(f"🧠 Planner prompt: {prompt}")

        response = await model.ainvoke(prompt)
        logger.info(f"🧠 Planner response: {response.content[:200]}...")
        # Return empty messages list to prevent appending - operator.add with [] is a no-op
        return {'thoughts': response.content, 'messages': []}

    async def use_tools(state: NPCState) -> NPCState:

        prompt = await tool_prompt_template.ainvoke(state.combined_dump)
        logger.debug(f"🔧 Tool prompt: {prompt}")

        tool_model = model.bind_tools(tools)

        tool_calls = await tool_model.ainvoke(prompt)
        logger.info(f"🔧 Tool response content: {tool_calls.content[:200] if tool_calls.content else 'None'}...")

        # Only add messages if tools were actually called
        # Don't add the AIMessage content (narrative) - only tool calls and results
        if not tool_calls.tool_calls:
            logger.info("🔧 No tools called, skipping message addition")
            return {'messages': []}

        # Create AIMessage with only tool_calls, stripping the narrative content
        tool_call_msg = AIMessage(content='', tool_calls=tool_calls.tool_calls)
        results = [tool_call_msg]

        for tcall in tool_calls.tool_calls:
            tool = tools_by_name[tcall['name']]
            result = await tool.ainvoke(tcall['args'])
            logger.info(f"🎲 Tool {tcall['name']} result: {result}")
            results.append(ToolMessage(content=result, tool_call_id=tcall["id"]))

        return {'messages': results}

    async def should_continue(state: NPCState) -> NPCState:
        pass

    async def npc_narrator(state: NPCState) -> NPCState:

        prompt = await narrator_prompt_template.ainvoke(state.combined_dump)

        response = await model.ainvoke(prompt)
        if not response.content.startswith(f"**{character.name}**: "):
            response.content = f"**{character.name}**: {response.content}"
        response.name = character.name
        response.id = str(uuid4())
        return {'messages': [response]}

    graph = StateGraph(NPCState)
    graph.add_node("memory_loader", memory_loader)
    graph.add_node("planner", planner)
    graph.add_node("use_tools", use_tools)
    # graph.add_node("should_continue", should_continue)
    graph.add_node("npc_narrator", npc_narrator)
    graph.add_edge(START, "memory_loader")
    graph.add_edge("memory_loader", "planner")
    graph.add_edge("planner", "use_tools")
    # graph.add_edge("use_tools", "should_continue")
    # graph.add_edge("should_continue", "npc_narrator")
    graph.add_edge("use_tools", "npc_narrator")
    graph.add_edge("npc_narrator", END)

    return graph.compile(name=character.name)