"""Generic lore-aware tool-loop agent, specialized as the lore creator and NPC builder."""
import asyncio
import operator
from logging import getLogger
from typing import Annotated, Literal

import openai
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode
from pydantic import BaseModel

from hephaestus.settings import settings

from database.graphiti_utils import load_information, make_group_id
from tools.lore_management import (
    bulk_save_lore_entries,
    delete_lore_entry,
    save_lore_entry,
    search_entities,
    search_lore,
)
from tools.npc_management import create_character
from utils.llm_models import lore_creator, npc_builder
from utils.prompts import lore_creator_prompt_template, npc_builder_prompt_template

info_limits = settings.graphiti.information_limits

logger = getLogger(__name__)

LORE_TOOLS = [search_lore, search_entities, save_lore_entry, bulk_save_lore_entries, delete_lore_entry]
BUILDER_TOOLS = [search_lore, search_entities, create_character]

# Model call resilience: the nano-gpt endpoint intermittently returns a
# server-side "Request timed out" SSE error (raised as openai.APIError) or
# silently stalls. Give each attempt a generous 3-minute cap and retry with
# backoff so a single flaky call doesn't kill the whole turn.
MODEL_TIMEOUT_S = 180.0
MODEL_MAX_ATTEMPTS = 3
MODEL_BACKOFF_S = (10.0, 20.0)

# Permanent client errors — retrying won't change the outcome, so fail fast.
_NON_RETRYABLE_API_ERRORS = (
    openai.BadRequestError,
    openai.AuthenticationError,
    openai.PermissionDeniedError,
    openai.NotFoundError,
    openai.UnprocessableEntityError,
    openai.ConflictError,
)


class ToolAgentState(BaseModel):
    messages: Annotated[list[AnyMessage], operator.add]
    world_name: str = ""
    existing_lore_context: str = ""


def spawn_tool_agent(
    world_name: str,
    *,
    tools: list,
    prompt_template: ChatPromptTemplate,
    model: BaseChatModel,
    name: str,
) -> StateGraph:
    """Build a multi-turn conversational agent that loads lore context for a world,
    then loops between an LLM node and its tools until no more tool calls are made.

    The returned graph is invoked per-message with the accumulated conversation
    history. State is in-memory only -- these chats are ephemeral.

    Designed for dual invocation:
      - By another agent: ``await graph.ainvoke({"messages": [HumanMessage(content=...)]})``
      - By a human: wrap with streaming via a Socket.IO event or API route.
    """

    async def load_context(state: ToolAgentState) -> dict:
        """🔍 Pull broad lore context from Graphiti so the agent knows
        what already exists in this world."""
        last_human = next((m for m in reversed(state.messages) if isinstance(m, HumanMessage)), None)
        if last_human is None:
            logger.warning(f"⚠️ [{name}] No human message found in state, skipping context load")
            return {"messages": [], "world_name": world_name}

        context = await load_information(
            query=last_human.content,
            group_ids=[make_group_id("lore", world_name)],
            limit=info_limits.lore,
        )
        logger.info(f"🌍 [{name}] Loaded {len(context.splitlines())} lore facts for world '{world_name}'")
        return {"messages": [], "world_name": world_name, "existing_lore_context": context}

    async def _invoke_model_with_retry(bound_model, prompt):
        """Call ``bound_model.ainvoke(prompt)`` with a 3-minute per-attempt cap
        and retry-with-backoff on transient upstream failures (timeouts,
        connection errors, server-side 'Request timed out' APIErrors).

        Permanent client errors (4xx) are re-raised immediately. After
        ``MODEL_MAX_ATTEMPTS`` transient failures the last error is re-raised
        so langfuse/langgraph still record the failure.
        """
        last_exc: Exception | None = None
        for attempt in range(1, MODEL_MAX_ATTEMPTS + 1):
            try:
                return await asyncio.wait_for(
                    bound_model.ainvoke(prompt), timeout=MODEL_TIMEOUT_S
                )
            except _NON_RETRYABLE_API_ERRORS as e:
                logger.error(f"🤖 [{name}] model call hit non-retryable {type(e).__name__}: {e}")
                raise
            except (openai.APIError, asyncio.TimeoutError) as e:
                last_exc = e
                if attempt >= MODEL_MAX_ATTEMPTS:
                    logger.error(
                        f"🤖 [{name}] model call failed after {attempt}/{MODEL_MAX_ATTEMPTS} "
                        f"attempts: {type(e).__name__}: {e}"
                    )
                    raise
                backoff = MODEL_BACKOFF_S[min(attempt - 1, len(MODEL_BACKOFF_S) - 1)]
                logger.warning(
                    f"🤖 [{name}] model call attempt {attempt}/{MODEL_MAX_ATTEMPTS} "
                    f"failed ({type(e).__name__}: {e}); retrying in {backoff:.0f}s"
                )
                await asyncio.sleep(backoff)
        # Defensive: should be unreachable.
        raise last_exc or RuntimeError(f"[{name}] model invoke failed without exception")

    async def agent(state: ToolAgentState) -> dict:
        """🧠 LLM agent that converses, asks follow-ups, and uses its tools."""
        prompt = await prompt_template.ainvoke({
            "messages": state.messages,
            "world_name": state.world_name,
            "existing_lore_context": state.existing_lore_context,
        })
        response = await _invoke_model_with_retry(model.bind_tools(tools), prompt)
        logger.info(f"🤖 [{name}] response for world '{world_name}', tool_calls={bool(response.tool_calls)}")
        return {"messages": [response]}

    def should_continue(state: ToolAgentState) -> Literal["tools", "__end__"]:
        last = state.messages[-1] if state.messages else None
        return "tools" if isinstance(last, AIMessage) and last.tool_calls else "__end__"

    graph = StateGraph(ToolAgentState)
    graph.add_node("load_context", load_context)
    graph.add_node("agent", agent)
    graph.add_node("tools", ToolNode(tools))

    graph.add_edge(START, "load_context")
    graph.add_edge("load_context", "agent")
    graph.add_conditional_edges("agent", should_continue, {"tools": "tools", "__end__": END})
    graph.add_edge("tools", "agent")

    return graph.compile(name=name)


def spawn_lore_creator(world_name: str) -> StateGraph:
    """Multi-turn lore creator/editor agent for a given world."""
    return spawn_tool_agent(
        world_name,
        tools=LORE_TOOLS,
        prompt_template=lore_creator_prompt_template,
        model=lore_creator,
        name="lore_creator",
    )


def spawn_npc_builder(world_name: str) -> StateGraph:
    """Multi-turn NPC builder agent that persists characters via create_character."""
    return spawn_tool_agent(
        world_name,
        tools=BUILDER_TOOLS,
        prompt_template=npc_builder_prompt_template,
        model=npc_builder,
        name="npc_builder",
    )
