"""Graph wiring for the DM supervisor.

Turn pipeline:

    START -> state_loader -> {graphiti_loader || intent_router} -> context_join
        -> ooc_responder -> persist_messages            (OOC short-circuit)
        -> rules_referee -> dm_planner -> continuity_checker
            -> dm_planner                               (one repair pass)
            -> {[npc build loop] || dm_narrator_opening} -> npc_executor
            -> dm_narrator_closing -> canon_manager -> turn_epilogue
        -> persist_messages -> END

Two fan-outs run concurrently:
  - Graphiti retrieval overlaps with intent classification; context_join
    waits for both before routing OOC vs story.
  - When the plan introduces NPCs, the build negotiation loop runs alongside
    opening narration; npc_executor is deferred so it starts only after both
    branches finish.
"""
from logging import getLogger

import socketio
from langgraph.graph import END, START, StateGraph

from agents.dungeon_master.builder import after_builder, make_builder_nodes
from agents.dungeon_master.canon import make_canon_manager, make_persist_messages
from agents.dungeon_master.context import DMContext, make_graphiti_loader, make_state_loader
from agents.dungeon_master.continuity import MAX_PLAN_ATTEMPTS, make_continuity_checker
from agents.dungeon_master.epilogue import make_turn_epilogue
from agents.dungeon_master.executor import make_npc_executor
from agents.dungeon_master.intent import make_intent_router, make_ooc_responder, route_intent
from agents.dungeon_master.narration import make_narrator_nodes
from agents.dungeon_master.planner import make_dm_planner
from agents.dungeon_master.referee import make_rules_referee
from agents.dungeon_master.schemas import DungeonMasterState
from database.models.conversation import Conversation

logger = getLogger(__name__)

SCENE_TARGETS = ["npc_builder_caller", "dm_narrator_opening", "npc_executor"]


def _route_to_scene(state: DungeonMasterState) -> str:
    plan = state.plan
    if plan is None:
        return "npc_executor"
    needs_narration = bool(
        plan.opening_narration
        or plan.time_location_update
        or plan.npcs_to_introduce
        # An action outcome alone only warrants narration when no NPC is
        # responding -- otherwise the NPCs carry the turn.
        or (plan.action_outcome and not plan.responding_npcs)
    )
    if needs_narration:
        return "dm_narrator_opening"
    logger.info("⏭️ Nothing to narrate, skipping straight to NPCs")
    return "npc_executor"


def _scene_fanout(state: DungeonMasterState) -> list[str]:
    """Targets to launch once the plan is final.

    With NPCs to build, the build loop and opening narration run as parallel
    branches; the deferred npc_executor waits for both to finish.
    """
    scene = _route_to_scene(state)
    if not state.build_queue:
        return [scene]
    if scene == "dm_narrator_opening":
        logger.info("🔀 Running NPC build loop and opening narration concurrently")
        return ["npc_builder_caller", "dm_narrator_opening"]
    return ["npc_builder_caller"]


def after_continuity(state: DungeonMasterState) -> list[str]:
    if state.continuity_notes and state.plan_attempts < MAX_PLAN_ATTEMPTS:
        return ["dm_planner"]
    return _scene_fanout(state)


def after_registrar(state: DungeonMasterState) -> str:
    # Opening narration already ran (or was skipped) in the parallel branch,
    # so the registrar only ever continues the build queue or hands off to
    # the deferred executor.
    return "npc_builder_caller" if state.build_queue else "npc_executor"


def after_npc_executor(state: DungeonMasterState) -> str:
    if state.plan and state.plan.closing_narration:
        return "dm_narrator_closing"
    return "canon_manager"


def spawn_dungeon_master(
    conversation: Conversation,
    sio: socketio.AsyncServer | None = None,
    sid: str | None = None,
    name: str = "dungeon_master",
) -> StateGraph:
    ctx = DMContext(conversation=conversation, sio=sio, sid=sid)

    async def context_join(state: DungeonMasterState) -> dict:
        """Barrier: waits for graphiti_loader and intent_router before routing."""
        return {"messages": []}

    nodes = {
        "state_loader": make_state_loader(ctx),
        "graphiti_loader": make_graphiti_loader(ctx),
        "intent_router": make_intent_router(ctx),
        "context_join": context_join,
        "ooc_responder": make_ooc_responder(ctx),
        "rules_referee": make_rules_referee(ctx),
        "dm_planner": make_dm_planner(ctx),
        "continuity_checker": make_continuity_checker(ctx),
        **make_builder_nodes(ctx),
        **make_narrator_nodes(ctx),
        "canon_manager": make_canon_manager(ctx),
        "turn_epilogue": make_turn_epilogue(ctx),
    }

    graph = StateGraph(DungeonMasterState)
    for node_name, node in nodes.items():
        graph.add_node(node_name, node)
    # Deferred nodes wait until all other in-flight branches finish, which
    # makes npc_executor the join point of the build-loop/narration fan-out.
    graph.add_node("npc_executor", make_npc_executor(ctx), defer=True)
    graph.add_node("persist_messages", make_persist_messages(ctx), defer=True)

    graph.add_edge(START, "state_loader")
    graph.add_edge("state_loader", "graphiti_loader")
    graph.add_edge("state_loader", "intent_router")
    graph.add_edge(["graphiti_loader", "intent_router"], "context_join")
    graph.add_conditional_edges("context_join", route_intent, ["ooc_responder", "rules_referee"])
    graph.add_edge("ooc_responder", "persist_messages")
    graph.add_edge("rules_referee", "dm_planner")
    graph.add_edge("dm_planner", "continuity_checker")
    graph.add_conditional_edges("continuity_checker", after_continuity, ["dm_planner", *SCENE_TARGETS])
    graph.add_conditional_edges("npc_builder_caller", after_builder, ["npc_build_reviewer", "npc_registrar"])
    graph.add_edge("npc_build_reviewer", "npc_builder_caller")
    graph.add_conditional_edges("npc_registrar", after_registrar, ["npc_builder_caller", "npc_executor"])
    graph.add_edge("dm_narrator_opening", "npc_executor")
    graph.add_conditional_edges("npc_executor", after_npc_executor, ["dm_narrator_closing", "canon_manager"])
    graph.add_edge("dm_narrator_closing", "canon_manager")
    graph.add_edge("canon_manager", "turn_epilogue")
    graph.add_edge("turn_epilogue", "persist_messages")
    graph.add_edge("persist_messages", END)

    return graph.compile(name=name)
