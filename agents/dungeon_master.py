import asyncio
import uuid
from typing import Annotated
import operator
from uuid import uuid4
from logging import getLogger

import socketio
from langchain_core.messages import AIMessage, AIMessageChunk, AnyMessage, HumanMessage
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from agents.nonplayer import spawn_npc_directed
from agents.npc_builder import build_npc
from database.graphiti_utils import (
    fire_and_forget,
    load_information,
    make_events_group_id,
    make_group_id,
    make_secrets_group_id,
    save_secret_notes,
    save_world_events,
)
from database.models import Character as CharacterModel
from database.models.conversation import Conversation
from database.postgres_connection import session as db_session
from utils.llm_models import dm_narrator_model, dm_planner_model
from utils.prompts import dm_narrator_prompt_template, dm_planner_prompt_template


logger = getLogger(__name__)

NARRATOR_NAME = "Narrator"

NODE_NARRATOR = "npc_narrator"


# ------------------------------------------------------------------
# Structured output models
# ------------------------------------------------------------------


class NPCDirective(BaseModel):
    """Instructions from the DM to a single NPC for this turn."""
    name: str = Field(description="Character name exactly as it appears in the active NPC list.")
    guidance: str = Field(description="What the DM wants this NPC to focus on, say, or do this turn.")
    withheld_info: list[str] = Field(
        default_factory=list,
        description="Facts this NPC must NOT reveal or reference (information asymmetry).",
    )


class NPCIntroduction(BaseModel):
    """Request from the DM to spawn a brand-new NPC mid-session."""
    name: str = Field(description="Desired name for the new character.")
    build_instructions: str = Field(
        description="Detailed instructions passed to the NPC builder describing "
                    "personality, appearance, role, and backstory.",
    )
    entrance_narration: str = Field(
        description="Brief note on how this NPC enters the scene "
                    "(expanded by the DM narrator).",
    )


class DMPlan(BaseModel):
    """The Dungeon Master's structured plan for this turn."""
    opening_narration: str | None = Field(
        default=None,
        description="Scene-setting or environmental narration BEFORE any NPC speaks. "
                    "None if no DM narration is needed.",
    )
    responding_npcs: list[NPCDirective] = Field(
        default_factory=list,
        description="Ordered list of NPCs that should respond this turn, "
                    "with per-NPC guidance. Empty if no NPC should speak.",
    )
    npcs_to_introduce: list[NPCIntroduction] = Field(
        default_factory=list,
        description="New NPCs to create and add to the scene. "
                    "Empty if no new NPCs are needed.",
    )
    npcs_to_dismiss: list[str] = Field(
        default_factory=list,
        description="Names of NPCs that leave the scene after this turn. "
                    "Empty if nobody leaves.",
    )
    closing_narration: str | None = Field(
        default=None,
        description="DM narration AFTER NPCs have spoken (consequences, cliffhangers). "
                    "None if not needed.",
    )
    new_world_events: list[str] = Field(
        default_factory=list,
        description="Significant facts or consequences to persist in the world event log. "
                    "Empty if nothing noteworthy happened.",
    )
    secret_notes: str | None = Field(
        default=None,
        description="DM-only knowledge that should be remembered for future turns "
                    "but NEVER revealed to NPCs or the player.",
    )
    action_outcome: str | None = Field(
        default=None,
        description="How the player's attempted action resolves. "
                    "Narrate failures as interesting story beats, not dead ends.",
    )
    time_location_update: str | None = Field(
        default=None,
        description="New location or time-of-day description if the scene changes. "
                    "None if the scene stays the same.",
    )


# ------------------------------------------------------------------
# DM graph state
# ------------------------------------------------------------------


class DungeonMasterState(BaseModel):
    messages: Annotated[list[AnyMessage], operator.add]


# ------------------------------------------------------------------
# NPC streaming helper
# ------------------------------------------------------------------


async def _stream_npc_to_socket(
    npc_graph: object,
    input_messages: list[AnyMessage],
    speaker: str,
    sio: socketio.AsyncServer,
    sid: str,
) -> tuple[list[AnyMessage], list[str]]:
    """Stream an NPC graph and emit tokens directly to a Socket.IO client.

    Runs the graph once via astream, forwards narrator chunks to the frontend,
    and reconstructs the final AIMessage from the accumulated content.

    Returns (delta_messages, streamed_message_ids).
    """
    message_id: str | None = None
    prefix_buffer = ""
    prefix_stripped = False
    streamed_ids: list[str] = []
    collected_content = ""

    stream = npc_graph.astream(
        {"messages": input_messages},
        stream_mode="messages",
        subgraphs=True,
    )

    async for namespace_tuple, (msg, metadata) in stream:
        langgraph_node = metadata.get("langgraph_node", "")

        if not isinstance(msg, AIMessageChunk) or langgraph_node != NODE_NARRATOR:
            continue

        if not msg.content:
            continue

        if message_id is None:
            message_id = str(uuid4())
            streamed_ids.append(message_id)
            await sio.emit("stream_start", {"messageId": message_id, "name": speaker}, to=sid)

        collected_content += msg.content
        token = msg.content

        if not prefix_stripped:
            prefix_buffer += token
            expected = f"{speaker}: "
            if len(prefix_buffer) >= len(expected):
                if prefix_buffer.startswith(expected):
                    remainder = prefix_buffer[len(expected):]
                    prefix_stripped = True
                    if remainder:
                        await sio.emit("stream_token", {"messageId": message_id, "token": remainder}, to=sid)
                else:
                    prefix_stripped = True
                    await sio.emit("stream_token", {"messageId": message_id, "token": prefix_buffer}, to=sid)
            elif not expected.startswith(prefix_buffer):
                prefix_stripped = True
                await sio.emit("stream_token", {"messageId": message_id, "token": prefix_buffer}, to=sid)
        else:
            await sio.emit("stream_token", {"messageId": message_id, "token": token}, to=sid)

    if message_id is not None:
        await sio.emit("stream_end", {"messageId": message_id}, to=sid)

    if not collected_content:
        return [], streamed_ids

    content = collected_content.strip()
    prefix = f"{speaker}:"
    if content.startswith(prefix):
        content = content[len(prefix):].lstrip()
    normalized = f"{speaker}: {content}"

    final_msg = AIMessage(content=normalized, name=speaker, id=message_id)
    return [final_msg], streamed_ids


# ------------------------------------------------------------------
# Graph builder
# ------------------------------------------------------------------


def spawn_dungeon_master(
    conversation: Conversation,
    sio: socketio.AsyncServer | None = None,
    sid: str | None = None,
    name: str = "dungeon_master",
) -> StateGraph:

    player = conversation.player
    campaign = conversation.campaign

    dm_plan_llm = dm_planner_model.with_structured_output(DMPlan, strict=True)

    # ------------------------------------------------------------------
    # Nodes
    # ------------------------------------------------------------------

    async def context_loader(state: DungeonMasterState) -> DungeonMasterState:
        """Load lore, world events, and DM secrets in parallel."""
        last_human = next(
            (m for m in reversed(state.messages) if isinstance(m, HumanMessage)),
            None,
        )
        query = last_human.content if last_human else "general scene"

        lore_task = load_information(
            query=query,
            group_ids=[make_group_id("lore", campaign.lore_world)],
            limit=15,
        )
        events_task = load_information(
            query=query,
            group_ids=[make_events_group_id(campaign.id)],
            limit=10,
        )
        secrets_task = load_information(
            query=query,
            group_ids=[make_secrets_group_id(campaign.id)],
            limit=10,
        )

        lore, events, secrets = await asyncio.gather(
            lore_task, events_task, secrets_task
        )

        logger.info(
            f"📚 Context loaded: {len(lore.splitlines())} lore, "
            f"{len(events.splitlines())} events, "
            f"{len(secrets.splitlines())} secrets"
        )

        conversation._dm_context = {
            "lore": lore,
            "world_events": events,
            "secret_knowledge": secrets,
        }

        return {"messages": []}

    async def dm_planner(state: DungeonMasterState) -> DungeonMasterState:
        """The DM brain: decide what happens this turn."""
        ctx = getattr(conversation, "_dm_context", {})

        active_descriptions = []
        for c in conversation.characters:
            active_descriptions.append(f"**{c.name}**:\n{c.description}")

        prompt = await dm_planner_prompt_template.ainvoke({
            "messages": [*conversation.message_buffer, *state.messages],
            "lore": ctx.get("lore", ""),
            "world_events": ctx.get("world_events", ""),
            "secret_knowledge": ctx.get("secret_knowledge", ""),
            "active_npcs": "\n\n".join(active_descriptions),
            "player": player.description,
            "location": conversation.location,
            "story_background": conversation.story_background,
        })

        plan: DMPlan = await dm_plan_llm.ainvoke(prompt)
        logger.info(
            f"🎲 DM plan: responding={[d.name for d in plan.responding_npcs]}, "
            f"introduce={[i.name for i in plan.npcs_to_introduce]}, "
            f"dismiss={plan.npcs_to_dismiss}"
        )

        conversation._dm_plan = plan

        return {"messages": []}

    async def npc_introducer(state: DungeonMasterState) -> DungeonMasterState:
        """Spawn new NPCs via the builder and register them."""
        plan: DMPlan | None = getattr(conversation, "_dm_plan", None)
        if not plan or not plan.npcs_to_introduce:
            return {"messages": []}

        conversation._npcs_introduced = True

        for intro in plan.npcs_to_introduce:
            try:
                logger.info(f"🏗️ Building new NPC: {intro.name}")
                await build_npc(campaign.lore_world, intro.build_instructions)

                character = db_session.query(CharacterModel).filter(
                    CharacterModel.name == intro.name
                ).first()

                if character is None:
                    logger.error(f"❌ NPC builder didn't create '{intro.name}' in DB")
                    continue

                conversation.add_character(character)
                logger.info(f"🎭 NPC '{intro.name}' introduced to scene")

            except Exception:
                logger.exception(f"❌ Failed to introduce NPC '{intro.name}'")

        return {"messages": []}

    async def dm_narrator_opening(state: DungeonMasterState) -> DungeonMasterState:
        """Expand opening narration notes into full prose."""
        plan: DMPlan | None = getattr(conversation, "_dm_plan", None)
        if not plan:
            return {"messages": []}

        notes_parts: list[str] = []
        if plan.action_outcome:
            notes_parts.append(f"Action outcome: {plan.action_outcome}")
        if plan.time_location_update:
            notes_parts.append(f"Scene change: {plan.time_location_update}")
        if plan.opening_narration:
            notes_parts.append(f"Opening narration: {plan.opening_narration}")

        for intro in plan.npcs_to_introduce:
            notes_parts.append(f"New character enters: {intro.entrance_narration}")

        if not notes_parts:
            return {"messages": []}

        prompt = await dm_narrator_prompt_template.ainvoke({
            "narration_notes": "\n".join(notes_parts),
            "location": conversation.location,
            "story_background": conversation.story_background,
            "messages": [*conversation.message_buffer, *state.messages],
        })

        response = await dm_narrator_model.ainvoke(prompt)
        content = response.content.strip()

        msg = AIMessage(content=content, name=NARRATOR_NAME, id=str(uuid4()))
        logger.info(f"📜 Opening narration: {content[:120]}...")
        return {"messages": [msg]}

    async def npc_executor(state: DungeonMasterState) -> DungeonMasterState:
        """Dynamically build and run each selected NPC in the DM's order."""
        plan: DMPlan | None = getattr(conversation, "_dm_plan", None)
        if not plan or not plan.responding_npcs:
            return {"messages": []}

        all_messages: list[AnyMessage] = []
        all_streamed_ids: list[str] = []

        for directive in plan.responding_npcs:
            character = next(
                (c for c in conversation.characters if c.name == directive.name),
                None,
            )
            if character is None:
                logger.warning(f"⚠️ NPC '{directive.name}' not found in conversation characters")
                continue

            npc_graph = spawn_npc_directed(character, conversation, directive)
            input_messages = [*state.messages, *all_messages]

            try:
                if sio is not None and sid is not None:
                    delta, streamed_ids = await _stream_npc_to_socket(
                        npc_graph, input_messages, character.name, sio, sid,
                    )
                    all_messages.extend(delta)
                    all_streamed_ids.extend(streamed_ids)
                else:
                    result = await npc_graph.ainvoke({"messages": input_messages})
                    delta = result.get("messages", [])[len(input_messages):]
                    all_messages.extend(delta)

                logger.info(f"🎭 {directive.name} produced {len(delta)} message(s)")
            except Exception:
                logger.exception(f"💥 NPC graph failed for '{directive.name}'")

        conversation._streamed_npc_ids = all_streamed_ids

        return {"messages": all_messages}

    async def dm_narrator_closing(state: DungeonMasterState) -> DungeonMasterState:
        """Expand closing narration notes into full prose."""
        plan: DMPlan | None = getattr(conversation, "_dm_plan", None)
        if not plan or not plan.closing_narration:
            return {"messages": []}

        prompt = await dm_narrator_prompt_template.ainvoke({
            "narration_notes": plan.closing_narration,
            "location": conversation.location,
            "story_background": conversation.story_background,
            "messages": [*conversation.message_buffer, *state.messages],
        })

        response = await dm_narrator_model.ainvoke(prompt)
        content = response.content.strip()

        msg = AIMessage(content=content, name=NARRATOR_NAME, id=str(uuid4()))
        logger.info(f"📜 Closing narration: {content[:120]}...")
        return {"messages": [msg]}

    async def consequence_tracker(state: DungeonMasterState) -> DungeonMasterState:
        """Persist world events and DM secrets to Graphiti, update location."""
        plan: DMPlan | None = getattr(conversation, "_dm_plan", None)
        if not plan:
            return {"messages": []}

        if plan.new_world_events:
            fire_and_forget(save_world_events(
                events=plan.new_world_events,
                campaign_id=campaign.id,
                lore_world=campaign.lore_world,
            ))

        if plan.secret_notes:
            fire_and_forget(save_secret_notes(
                notes=plan.secret_notes,
                campaign_id=campaign.id,
                lore_world=campaign.lore_world,
            ))

        if plan.time_location_update:
            conversation.location = plan.time_location_update
            db_session.add(conversation)
            db_session.commit()
            logger.info(f"📍 Location updated: {plan.time_location_update}")

        for dismissed in plan.npcs_to_dismiss:
            logger.info(f"👋 {dismissed} dismissed from scene")

        return {"messages": []}

    async def persist_messages(state: DungeonMasterState) -> DungeonMasterState:
        """Write all messages from this turn to the DB and message buffer."""
        for message in state.messages:
            if message.id is None:
                message.id = str(uuid4())
            if isinstance(message, HumanMessage):
                message.name = player.name

        conversation.message_buffer.extend(state.messages)

        for message in state.messages:
            msg_uuid = uuid.UUID(message.id) if message.id else None
            conversation.add_message(
                message.type, message.content, message.name, _id=msg_uuid
            )

        ids = [msg.id for msg in conversation.message_buffer]
        dupes = len(ids) - len(set(ids))
        if dupes:
            logger.error(f"👯‍♀️ {dupes} duplicate message IDs detected")

        conversation._dm_plan = None

        return {"messages": []}

    # ------------------------------------------------------------------
    # Conditional edges
    # ------------------------------------------------------------------

    def after_introducer(state: DungeonMasterState) -> str:
        plan: DMPlan | None = getattr(conversation, "_dm_plan", None)
        has_narration = plan and (
            plan.opening_narration
            or plan.action_outcome
            or plan.time_location_update
            or plan.npcs_to_introduce
        )
        if has_narration:
            return "dm_narrator_opening"
        return "npc_executor"

    def after_npc_executor(state: DungeonMasterState) -> str:
        plan: DMPlan | None = getattr(conversation, "_dm_plan", None)
        if plan and plan.closing_narration:
            return "dm_narrator_closing"
        return "consequence_tracker"

    # ------------------------------------------------------------------
    # Build the graph
    # ------------------------------------------------------------------

    graph = StateGraph(DungeonMasterState)

    graph.add_node("context_loader", context_loader)
    graph.add_node("dm_planner", dm_planner)
    graph.add_node("npc_introducer", npc_introducer)
    graph.add_node("dm_narrator_opening", dm_narrator_opening)
    graph.add_node("npc_executor", npc_executor)
    graph.add_node("dm_narrator_closing", dm_narrator_closing)
    graph.add_node("consequence_tracker", consequence_tracker)
    graph.add_node("persist_messages", persist_messages, defer=True)

    graph.add_edge(START, "context_loader")
    graph.add_edge("context_loader", "dm_planner")
    graph.add_edge("dm_planner", "npc_introducer")
    graph.add_conditional_edges("npc_introducer", after_introducer)
    graph.add_edge("dm_narrator_opening", "npc_executor")
    graph.add_conditional_edges("npc_executor", after_npc_executor)
    graph.add_edge("dm_narrator_closing", "consequence_tracker")
    graph.add_edge("consequence_tracker", "persist_messages")
    graph.add_edge("persist_messages", END)

    return graph.compile(name=name)
