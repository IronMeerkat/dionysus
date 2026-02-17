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

from tools.dice import roll_d20, roll_d10, roll_d6
from utils.prompts import plan_prompt_template, tool_prompt_template, narrator_prompt_template

logger = getLogger(__name__)

model = ChatXAI(
    model="grok-4-1-fast-reasoning",
    temperature=1,
    callbacks=[langfuse_callback_handler],
    max_retries=3,
)



tools = [roll_d20, roll_d10, roll_d6]
tools_by_name = {tool.name: tool for tool in tools}

def spawn_npc(_name: str, _description: str, _player_description: str) -> StateGraph:

    class NPCState(BaseModel):
        messages: Annotated[list[AnyMessage], operator.add]
        player: str = _player_description
        name: str = _name
        description: str = _description
        thoughts: str = ''

    def planner(state: NPCState) -> NPCState:

        prompt = plan_prompt_template.invoke(state.model_dump(exclude={'thoughts'}))
        logger.debug(f"🧠 Planner prompt: {prompt}")

        response = model.invoke(prompt)
        logger.info(f"🧠 Planner response: {response.content[:200]}...")
        # Return empty messages list to prevent appending - operator.add with [] is a no-op
        return {'thoughts': response.content, 'messages': []}

    def use_tools(state: NPCState) -> NPCState:

        prompt = tool_prompt_template.invoke(state.model_dump(exclude={'player'}))
        logger.debug(f"🔧 Tool prompt: {prompt}")

        tool_model = model.bind_tools(tools)

        tool_calls = tool_model.invoke(prompt)
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
            result = tool.invoke(tcall['args'])
            logger.info(f"🎲 Tool {tcall['name']} result: {result}")
            results.append(ToolMessage(content=result, tool_call_id=tcall["id"]))

        return {'messages': results}

    def should_continue(state: NPCState) -> NPCState:
        pass

    def npc_narrator(state: NPCState) -> NPCState:

        prompt = narrator_prompt_template.invoke(state.model_dump(exclude={'player'}))

        response = model.invoke(prompt)
        return {'messages': [response]}

    graph = StateGraph(NPCState)
    graph.add_node("planner", planner)
    graph.add_node("use_tools", use_tools)
    # graph.add_node("should_continue", should_continue)
    graph.add_node("npc_narrator", npc_narrator)
    graph.add_edge(START, "planner")
    graph.add_edge("planner", "use_tools")
    # graph.add_edge("use_tools", "should_continue")
    # graph.add_edge("should_continue", "npc_narrator")
    graph.add_edge("use_tools", "npc_narrator")
    graph.add_edge("npc_narrator", END)

    planner = graph.compile(name=_name)

    return planner