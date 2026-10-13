"""Closing narrator node for the DM pipeline."""
from langchain_core.messages import AIMessage
from langgraph.graph.state import CompiledStateGraph

from agents.dungeon_master.schemas import DMContext, NARRATOR_NAME, narrate_beats
from contracts.turn_events import DICE_SPEAKER
from hephaestus.agent_architectures import AgentSwarmState, function_to_graph


def spawn_dm_narrator_closing(ctx: DMContext) -> CompiledStateGraph:
    async def dm_narrator_closing(state: AgentSwarmState) -> dict:
        plan = ctx.plan
        if ctx.ooc or not plan:
            return {"messages": []}
        notes: list[tuple[str, str]] = []
        npc_spoke = any(
            isinstance(m, AIMessage) and m.name not in (None, NARRATOR_NAME, DICE_SPEAKER)
            for m in state.messages
        )
        if plan.action_outcome and not ctx.outcome_narrated and not npc_spoke:
            notes.append(("Action outcome", plan.action_outcome))
        if plan.closing_narration:
            notes.append(("Closing narration", plan.closing_narration))
        return {"messages": await narrate_beats(ctx, notes, state.messages)}

    return function_to_graph(dm_narrator_closing, name="dm_narrator_closing")
