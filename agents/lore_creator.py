from logging import getLogger
from typing import Annotated, Literal
import operator

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode
from pydantic import BaseModel, Field

from database.graphiti_utils import load_information, make_group_id
from tools.lore_management import (
    delete_lore_entry,
    save_lore_entry,
    search_entities,
    search_lore,
)
from utils.llm_models import lore_creator
from utils.prompts import lore_creator_prompt_template

logger = getLogger(__name__)

LORE_TOOLS = [search_lore, search_entities, save_lore_entry, delete_lore_entry]


class LoreCreatorState(BaseModel):
    messages: Annotated[list[AnyMessage], operator.add]
    world_name: str = ""
    existing_lore_context: str = ""


def spawn_lore_creator(world_name: str) -> StateGraph:
    """Build a multi-turn lore creator/editor agent for a given world.

    The returned graph is invoked per-message with the accumulated
    conversation history.  State is in-memory only -- lore editing
    chats are ephemeral and not persisted to the database.
    """

    async def load_context(state: LoreCreatorState) -> dict:
        """🔍 Pull broad lore context from Graphiti so the agent knows
        what already exists in this world."""
        last_human = next(
            (m for m in reversed(state.messages) if isinstance(m, HumanMessage)),
            None,
        )
        if last_human is None:
            logger.warning("⚠️ No human message found in state, skipping context load")
            return {"messages": [], "world_name": world_name}

        group_id = make_group_id("lore", world_name)
        context = await load_information(
            query=last_human.content,
            group_ids=[group_id],
            limit=20,
        )
        logger.info(f"🌍 Loaded {len(context.splitlines())} lore facts for world '{world_name}'")
        return {
            "messages": [],
            "world_name": world_name,
            "existing_lore_context": context,
        }

    async def lore_agent(state: LoreCreatorState) -> dict:
        """🧠 LLM agent that converses about lore, asks follow-ups,
        and uses tools to search/save/delete entries."""
        prompt = await lore_creator_prompt_template.ainvoke({
            "messages": state.messages,
            "world_name": state.world_name,
            "existing_lore_context": state.existing_lore_context,
        })

        model = lore_creator.bind_tools(LORE_TOOLS)
        response = await model.ainvoke(prompt)
        logger.info(
            f"📝 Lore agent response for '{world_name}', "
            f"tool_calls={bool(response.tool_calls)}"
        )
        return {"messages": [response]}

    def should_continue(state: LoreCreatorState) -> Literal["tools", "__end__"]:
        if not state.messages:
            return "__end__"
        last = state.messages[-1]
        if isinstance(last, AIMessage) and last.tool_calls:
            return "tools"
        return "__end__"

    graph = StateGraph(LoreCreatorState)
    graph.add_node("load_context", load_context)
    graph.add_node("lore_agent", lore_agent)
    graph.add_node("tools", ToolNode(LORE_TOOLS))

    graph.add_edge(START, "load_context")
    graph.add_edge("load_context", "lore_agent")
    graph.add_conditional_edges(
        "lore_agent",
        should_continue,
        {"tools": "tools", "__end__": END},
    )
    graph.add_edge("tools", "lore_agent")

    return graph.compile(name="lore_creator")
