"""Graph wiring for the DM supervisor."""
from langgraph.graph.state import CompiledStateGraph

from agents.dungeon_master.dm_narrator_closing import spawn_dm_narrator_closing
from agents.dungeon_master.dm_narrator_opening import spawn_dm_narrator_opening
from agents.dungeon_master.dm_planner import spawn_dm_planner
from agents.dungeon_master.npc_swarm import spawn_npc_swarm
from agents.dungeon_master.ooc_responder import spawn_ooc_responder
from agents.dungeon_master.persist_messages import spawn_persist_messages
from agents.dungeon_master.schemas import DMContext
from agents.dungeon_master.state_loader import spawn_state_loader
from contracts.sinks import NullTurnSink
from contracts.turn_events import TurnSink
from database.models.conversation import Conversation
from hephaestus.agent_architectures import create_daisy_chain


def spawn_dungeon_master(
    conversation: Conversation,
    sink: TurnSink | None = None,
    name: str = "dungeon_master",
) -> CompiledStateGraph:
    """🧙‍♂️ Build the DM turn pipeline using ``create_daisy_chain``."""
    ctx = DMContext(conversation=conversation, sink=sink or NullTurnSink())
    return create_daisy_chain(
        spawn_state_loader(ctx),
        spawn_ooc_responder(ctx),
        spawn_dm_planner(ctx),
        spawn_dm_narrator_opening(ctx),
        spawn_npc_swarm(ctx),
        spawn_dm_narrator_closing(ctx),
        spawn_persist_messages(ctx),
        name=name,
    )
