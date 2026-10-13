"""Dynamic NPC swarm subgraph and turn router."""
from logging import getLogger

from langchain_core.messages import AIMessage, SystemMessage
from langgraph.graph.state import CompiledStateGraph

from agents.dungeon_master.schemas import DMContext, NARRATOR_CONTEXT_WINDOW
from agents.nonplayer import spawn_npc
from hephaestus.agent_architectures import AgentSwarmState, create_dynamic_daisy_chain, function_to_graph
from utils.llm_models import dm_continuity_model

logger = getLogger(__name__)


def spawn_npc_swarm(ctx: DMContext) -> CompiledStateGraph:
    conversation = ctx.conversation

    async def npc_router(state: AgentSwarmState) -> dict:
        if ctx.ooc or not conversation.characters:
            return {"messages": [AIMessage(content="done")]}
        spoken = {m.name for m in state.messages if isinstance(m, AIMessage) and m.name}
        remaining = [c.name for c in conversation.characters if c.name not in spoken]
        if not remaining:
            return {"messages": [AIMessage(content="done")]}
        try:
            outcome = (ctx.plan.action_outcome or "none") if ctx.plan else "none"
            resp = await dm_continuity_model.ainvoke([
                SystemMessage(content=(
                    f"You are the turn router for a TTRPG scene at {ctx.location}. "
                    f"Active NPCs who have not yet spoken this turn: {', '.join(remaining)}. "
                    f"NPC states:\n{ctx.active_npc_states}\nAction outcome: {outcome}\n"
                    f"Pick the single next NPC from {remaining} who should respond right now, "
                    f"or reply 'done' if no more NPCs need to speak. Reply with ONLY the exact name or 'done'."
                )),
                *ctx.combined_messages(state.messages, limit=NARRATOR_CONTEXT_WINDOW),
            ])
            choice = (resp.content or "done").strip()
            return {"messages": [AIMessage(content=choice if choice in remaining else "done")]}
        except Exception:
            logger.exception("💥 NPC router failed; ending NPC turns")
            return {"messages": [AIMessage(content="done")]}

    return create_dynamic_daisy_chain(
        *(spawn_npc(c, ctx) for c in conversation.characters),
        router_agent=function_to_graph(npc_router, name="npc_router"),
        name="npc_swarm",
    )
