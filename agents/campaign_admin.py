"""Out-of-character campaign admin agent.

A multi-turn conversational agent that lets the organizer discuss and edit a
campaign's configuration -- story background, the story contract, current
scene location, narrative clock, quest threads and faction clocks -- without
entering play. Mirrors the tool-loop shape of ``agents.tool_agent`` but loads a
campaign overview (from Postgres) instead of lore context (from Graphiti), and
binds its tools to a single ``campaign_id``.

The returned graph is invoked per-message with the accumulated conversation
history. State is in-memory only -- these chats are ephemeral.
"""
import operator
from logging import getLogger
from typing import Annotated, Literal

from langchain_core.messages import AIMessage, AnyMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode
from pydantic import BaseModel

from tools.campaign_admin import build_campaign_admin_tools, render_campaign_overview
from utils.llm_models import campaign_admin as campaign_admin_model
from utils.prompts import campaign_admin_prompt_template

logger = getLogger(__name__)


class CampaignAdminState(BaseModel):
    messages: Annotated[list[AnyMessage], operator.add]
    campaign_id: int
    campaign_context: str = ""


def spawn_campaign_admin(campaign_id: int) -> StateGraph:
    """Build the multi-turn campaign-admin agent bound to one campaign."""

    tools = build_campaign_admin_tools(campaign_id)

    async def load_context(state: CampaignAdminState) -> dict:
        """📋 Pull the campaign's current configuration so the agent always
        starts a turn from the latest DB state."""
        context = render_campaign_overview(campaign_id)
        logger.info(f"📋 [campaign_admin] Loaded overview for campaign {campaign_id}")
        return {"messages": [], "campaign_context": context}

    async def agent(state: CampaignAdminState) -> dict:
        """🧑‍💼 OOC admin assistant: converses, asks follow-ups, and uses its tools."""
        prompt = await campaign_admin_prompt_template.ainvoke({
            "messages": state.messages,
            "campaign_context": state.campaign_context,
            "campaign_id": state.campaign_id,
        })
        response = await campaign_admin_model.bind_tools(tools).ainvoke(prompt)
        logger.info(
            f"🧑‍💼 [campaign_admin] response for campaign {campaign_id}, "
            f"tool_calls={bool(response.tool_calls)}"
        )
        return {"messages": [response]}

    def should_continue(state: CampaignAdminState) -> Literal["tools", "__end__"]:
        last = state.messages[-1] if state.messages else None
        return "tools" if isinstance(last, AIMessage) and last.tool_calls else "__end__"

    graph = StateGraph(CampaignAdminState)
    graph.add_node("load_context", load_context)
    graph.add_node("agent", agent)
    graph.add_node("tools", ToolNode(tools))

    graph.add_edge(START, "load_context")
    graph.add_edge("load_context", "agent")
    graph.add_conditional_edges("agent", should_continue, {"tools": "tools", "__end__": END})
    graph.add_edge("tools", "agent")

    return graph.compile(name="campaign_admin")
