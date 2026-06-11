from logging import getLogger
from typing import Annotated, Literal
import operator

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode
from pydantic import BaseModel, Field

from database.graphiti_utils import load_information, make_group_id
from tools.lore_management import search_lore, search_entities
from tools.npc_management import create_character
from utils.llm_models import npc_builder
from utils.prompts import npc_builder_prompt_template

logger = getLogger(__name__)

BUILDER_TOOLS = [search_lore, search_entities, create_character]


class NPCBuilderState(BaseModel):
    messages: Annotated[list[AnyMessage], operator.add]
    world_name: str = ""
    existing_lore_context: str = ""


def spawn_npc_builder(world_name: str) -> StateGraph:
    """Build a multi-turn NPC builder/editor agent for a given world.

    The returned graph is invoked per-message with the accumulated
    conversation history.  The agent converses about NPC design, asks
    follow-ups, and persists finished characters to the database via the
    create_character tool.

    Designed for dual invocation:
      - By another agent: ``await graph.ainvoke({"messages": [HumanMessage(content=...)]})``
      - By a human: wrap with streaming via a Socket.IO event or API route.
    """

    async def load_lore(state: NPCBuilderState) -> dict:
        """🔍 Fetch broad lore context from Graphiti so the builder
        knows the world before designing an NPC."""
        last_human = next(
            (m for m in reversed(state.messages) if isinstance(m, HumanMessage)),
            None,
        )
        if last_human is None:
            logger.warning("⚠️ No human message found in state, skipping lore load")
            return {"messages": [], "world_name": world_name}

        group_id = make_group_id("lore", world_name)
        context = await load_information(
            query=last_human.content,
            group_ids=[group_id],
            limit=50,
        )
        logger.info(f"🌍 Loaded {len(context.splitlines())} lore facts for world '{world_name}'")
        return {
            "messages": [],
            "world_name": world_name,
            "existing_lore_context": context,
        }

    async def builder_agent(state: NPCBuilderState) -> dict:
        """🧠 LLM agent that converses about NPC design, asks follow-ups,
        and persists finished characters via the create_character tool."""
        prompt = await npc_builder_prompt_template.ainvoke({
            "messages": state.messages,
            "world_name": state.world_name,
            "existing_lore_context": state.existing_lore_context,
        })

        model = npc_builder.bind_tools(BUILDER_TOOLS)
        response = await model.ainvoke(prompt)
        logger.info(
            f"🏗️ Builder agent response for world '{world_name}', "
            f"tool_calls={bool(response.tool_calls)}"
        )
        return {"messages": [response]}

    def should_continue(state: NPCBuilderState) -> Literal["tools", "__end__"]:
        if not state.messages:
            return "__end__"
        last = state.messages[-1]
        if isinstance(last, AIMessage) and last.tool_calls:
            return "tools"
        return "__end__"

    graph = StateGraph(NPCBuilderState)
    graph.add_node("load_lore", load_lore)
    graph.add_node("builder_agent", builder_agent)
    graph.add_node("tools", ToolNode(BUILDER_TOOLS))

    graph.add_edge(START, "load_lore")
    graph.add_edge("load_lore", "builder_agent")
    graph.add_conditional_edges(
        "builder_agent",
        should_continue,
        {"tools": "tools", "__end__": END},
    )
    graph.add_edge("tools", "builder_agent")

    return graph.compile(name="npc_builder")
