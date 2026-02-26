from logging import getLogger
from typing import Annotated, Literal
import operator

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langchain_xai import ChatXAI
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode
from pydantic import BaseModel, Field

from database.graphiti_utils import load_information, make_group_id
from database.models.conversation import Conversation
from tools.npc_management import create_character
from utils.prompts import npc_creator_prompt_template

logger = getLogger(__name__)

NPC_TOOLS = [create_character]


class NPCManagerState(BaseModel):
    messages: Annotated[list[AnyMessage], operator.add] 
    memories: str = Field(default='')


def spawn_npc_manager(conversation: Conversation) -> StateGraph:
    """Build a standalone graph agent that uses tools to create a new NPC from conversation context."""

    async def memories_loader(state: NPCManagerState) -> NPCManagerState:
        last_human_message = next(m for m in reversed(state.messages) if isinstance(m, HumanMessage))

        lore = await load_information(
            query=last_human_message.content,
            group_ids=[make_group_id("lore", conversation.lore_world)],
            limit=20,
        )

        character_group_ids = [make_group_id("memories", c.name) for c in conversation.characters]
        episodic_memories = await load_information(
            query=last_human_message.content,
            group_ids=character_group_ids,
            limit=10,
        )

        combined = "\n".join(part for part in [episodic_memories, lore] if part)
        return {'memories': combined, 'messages': []}

    async def agent_node(state: NPCManagerState) -> dict:
        """LLM agent that uses tools to create a new NPC."""
        messages = [*conversation.message_buffer, *state.messages]
        prompt = await npc_creator_prompt_template.ainvoke({
            "messages": messages,
            "memories": state.memories,
            "location": conversation.location,
            "story_background": conversation.story_background,
            "player": conversation.player.description,
            "other_characters": '\n\n\n'.join([f"**{c.name}**:\n{c.description}" for c in conversation.characters]),
        })

        model = ChatXAI(
            model="grok-4-1-fast-reasoning",
            temperature=0.8,
            max_retries=3,
        ).bind_tools(NPC_TOOLS)

        response = await model.ainvoke(prompt)
        logger.info(f"🎭 Agent response, tool_calls={bool(response.tool_calls)}")
        return {"messages": [response]}

    def should_continue(state: NPCManagerState) -> Literal["tools", "__end__"]:
        """Route to tools if the LLM made tool calls, otherwise end."""
        if not state.messages:
            return "__end__"
        last = state.messages[-1]
        if isinstance(last, AIMessage) and last.tool_calls:
            return "tools"
        return "__end__"

    graph = StateGraph(NPCManagerState)
    graph.add_node("memories_loader", memories_loader)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", ToolNode(NPC_TOOLS))

    graph.add_edge(START, "memories_loader")
    graph.add_edge("memories_loader", "agent")
    graph.add_conditional_edges("agent", should_continue, {"tools": "tools", "__end__": END})
    graph.add_edge("tools", "agent")

    return graph.compile(name="npc_manager")
