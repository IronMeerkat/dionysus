import asyncio
import operator
from logging import getLogger
from typing import Annotated
from uuid import UUID, uuid4

import socketio
from langchain_core.messages import AIMessage, AIMessageChunk, AnyMessage, HumanMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from agents.nonplayer import spawn_npc_directed
from agents.npc_builder import spawn_npc_builder
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
from utils.prompts import (
    dm_narrator_prompt_template,
    dm_npc_reviewer_prompt_template,
    dm_planner_prompt_template,
)

logger = getLogger(__name__)

NARRATOR_NAME = "Narrator"
NODE_NARRATOR = "npc_narrator"
# Max DM<->builder argument rounds per NPC before the DM forces approval.
MAX_BUILD_ROUNDS = 3


class NPCDirective(BaseModel):
    """Instructions from the DM to a single NPC for this turn."""
    name: str = Field(description="Character name exactly as it appears in the active NPC list.")
    guidance: str = Field(description="What the DM wants this NPC to focus on, say, or do this turn.")
    withheld_info: list[str] = Field(default_factory=list, description=(
        "Facts this NPC must NOT reveal or reference (information asymmetry)."))


class NPCIntroduction(BaseModel):
    """Request from the DM to spawn a brand-new NPC mid-session."""
    name: str = Field(description="Desired name for the new character.")
    build_instructions: str = Field(description=(
        "Detailed instructions passed to the NPC builder describing "
        "personality, appearance, role, and backstory."))
    entrance_narration: str = Field(description=(
        "Brief note on how this NPC enters the scene (expanded by the DM narrator)."))


class DMPlan(BaseModel):
    """The Dungeon Master's structured plan for this turn."""
    opening_narration: str | None = Field(default=None, description=(
        "OPTIONAL scene-setting or environmental narration BEFORE any NPC speaks. Most turns need "
        "none -- leave None whenever NPC dialogue alone carries the moment."))
    responding_npcs: list[NPCDirective] = Field(default_factory=list, description=(
        "Ordered list of NPCs that should respond this turn, with per-NPC guidance. "
        "Empty if no NPC should speak."))
    npcs_to_introduce: list[NPCIntroduction] = Field(default_factory=list, description=(
        "New NPCs to create and add to the scene. Empty if no new NPCs are needed."))
    # npcs_to_dismiss: list[str] = Field(default_factory=list, description=(
    #     "Names of NPCs that leave the scene after this turn. Empty if nobody leaves."))
    closing_narration: str | None = Field(default=None, description=(
        "OPTIONAL DM narration AFTER NPCs have spoken (consequences, cliffhangers). Most turns need "
        "none -- leave None unless the moment genuinely demands a narrative beat."))
    new_world_events: list[str] = Field(default_factory=list, description=(
        "Significant facts or consequences to persist in the world event log. "
        "Empty if nothing noteworthy happened."))
    secret_notes: str | None = Field(default=None, description=(
        "DM-only knowledge that should be remembered for future turns "
        "but NEVER revealed to NPCs or the player."))
    action_outcome: str | None = Field(default=None, description=(
        "How the player's attempted action resolves. Only set when the player actually attempts "
        "an action with an uncertain outcome -- None for plain dialogue. Narrate failures as "
        "interesting story beats, not dead ends."))
    time_location_update: str | None = Field(default=None, description=(
        "New location or time-of-day description if the scene changes. "
        "None if the scene stays the same."))


class BuildReview(BaseModel):
    """The DM's verdict on a character card drafted by the NPC builder."""
    approved: bool = Field(description=(
        "True only if a complete, on-brief W++ card with the exact requested name was presented."))
    feedback: str = Field(description=(
        "Answers to the builder's questions, or specific critique of the card. "
        "Confirmation text if approved."))


class DungeonMasterState(BaseModel):
    messages: Annotated[list[AnyMessage], operator.add]
    plan: DMPlan | None = None
    lore: str = ""
    world_events: str = ""
    secret_knowledge: str = ""
    # NPC build negotiation loop (DM <-> npc_builder argument)
    build_queue: list[NPCIntroduction] = Field(default_factory=list)
    build_transcript: list[AnyMessage] = Field(default_factory=list)
    build_rounds: int = 0
    build_created: bool = False


async def _stream_npc_to_socket(
    npc_graph: object,
    input_messages: list[AnyMessage],
    speaker: str,
    sio: socketio.AsyncServer,
    sid: str,
) -> list[AnyMessage]:
    """Stream an NPC graph and emit tokens directly to a Socket.IO client.

    Tokens are forwarded live for responsiveness, but the *authoritative* message is
    the cleaned one the npc_narrator node returns (prefix-stripping, foreign-turn
    truncation, retries) -- raw chunks may contain several retry attempts concatenated.
    ``stream_end`` carries the cleaned content so the frontend can snap the live
    bubble to it (or drop the bubble when narration failed entirely).

    Returns the cleaned delta messages, carrying the streamed bubble id.
    """
    message_id: str | None = None
    prefix_buffer = ""
    prefix_stripped = False
    final_messages: list[AnyMessage] = []
    expected = f"{speaker}: "

    async def ensure_started() -> None:
        nonlocal message_id
        if message_id is None:
            message_id = str(uuid4())
            await sio.emit("stream_start", {"messageId": message_id, "name": speaker}, to=sid)

    stream = npc_graph.astream(
        {"messages": input_messages}, stream_mode=["messages", "updates"], subgraphs=True,
    )

    async for _namespace, mode, payload in stream:
        if mode == "updates":
            for node_name, update in payload.items():
                if node_name == NODE_NARRATOR and update:
                    final_messages = list(update.get("messages") or [])
            continue

        msg, metadata = payload
        if (
            not isinstance(msg, AIMessageChunk)
            or metadata.get("langgraph_node", "") != NODE_NARRATOR
            or not msg.content
        ):
            continue

        await ensure_started()
        if prefix_stripped:
            await sio.emit("stream_token", {"messageId": message_id, "token": msg.content}, to=sid)
            continue

        # Buffer until the leading "{speaker}: " prefix is either stripped or ruled out.
        prefix_buffer += msg.content
        if len(prefix_buffer) >= len(expected) or not expected.startswith(prefix_buffer):
            prefix_stripped = True
            flush = prefix_buffer[len(expected):] if prefix_buffer.startswith(expected) else prefix_buffer
            if flush:
                await sio.emit("stream_token", {"messageId": message_id, "token": flush}, to=sid)

    if not final_messages:
        if message_id is not None:
            # Narration failed after retries: retract the live bubble.
            logger.warning(f"🗑️ {speaker}: no usable narration, retracting streamed bubble {message_id}")
            await sio.emit("stream_end", {"messageId": message_id, "content": ""}, to=sid)
        return []

    final_msg = final_messages[-1]
    display_content = final_msg.content
    if display_content.startswith(f"{speaker}:"):
        display_content = display_content[len(speaker) + 1:].lstrip()

    await ensure_started()
    # Reuse the bubble id so the persisted DB row and the frontend agree.
    final_msg.id = message_id
    await sio.emit("stream_end", {"messageId": message_id, "content": display_content}, to=sid)
    return final_messages


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


def after_plan_or_registrar(state: DungeonMasterState) -> str:
    return "npc_builder_caller" if state.build_queue else _route_to_scene(state)


def after_builder(state: DungeonMasterState) -> str:
    if state.build_created:
        return "npc_registrar"
    if state.build_rounds >= MAX_BUILD_ROUNDS:
        logger.error("🛑 Builder never persisted the NPC despite forced approval, giving up")
        return "npc_registrar"
    return "npc_build_reviewer"


def after_npc_executor(state: DungeonMasterState) -> str:
    if state.plan and state.plan.closing_narration:
        return "dm_narrator_closing"
    return "consequence_tracker"


def spawn_dungeon_master(
    conversation: Conversation,
    sio: socketio.AsyncServer | None = None,
    sid: str | None = None,
    name: str = "dungeon_master",
) -> StateGraph:

    player = conversation.player
    campaign = conversation.campaign

    dm_plan_llm = dm_planner_model.with_structured_output(DMPlan, strict=True)
    dm_review_llm = dm_planner_model.with_structured_output(BuildReview, strict=True)

    async def context_loader(state: DungeonMasterState) -> dict:
        """Load lore, world events, and DM secrets in parallel."""
        last_human = next((m for m in reversed(state.messages) if isinstance(m, HumanMessage)), None)
        query = last_human.content if last_human else "general scene"

        group_ids = [
            make_group_id("lore", campaign.lore_world),
            make_events_group_id(campaign.id),
            make_secrets_group_id(campaign.id),
        ]
        lore, events, secrets = await asyncio.gather(
            *(load_information(query=query, group_ids=[gid], limit=40) for gid in group_ids)
        )
        logger.info(
            f"📚 Context loaded: {len(lore.splitlines())} lore, "
            f"{len(events.splitlines())} events, {len(secrets.splitlines())} secrets"
        )
        return {"messages": [], "lore": lore, "world_events": events, "secret_knowledge": secrets}

    async def dm_planner(state: DungeonMasterState) -> dict:
        """The DM brain: decide what happens this turn."""
        prompt = await dm_planner_prompt_template.ainvoke({
            "messages": [*conversation.message_buffer, *state.messages],
            "lore": state.lore,
            "world_events": state.world_events,
            "secret_knowledge": state.secret_knowledge,
            "active_npcs": "\n\n".join(f"**{c.name}**:\n{c.description}" for c in conversation.characters),
            "player": player.description,
            "location": conversation.location,
            "story_background": conversation.story_background,
        })

        plan: DMPlan = await dm_plan_llm.ainvoke(prompt)
        # logger.info(
        #     f"🎲 DM plan: responding={[d.name for d in plan.responding_npcs]}, "
        #     f"introduce={[i.name for i in plan.npcs_to_introduce]}, dismiss={plan.npcs_to_dismiss}"
        # )
        return {"messages": [], "plan": plan, "build_queue": list(plan.npcs_to_introduce)}

    async def npc_builder_caller(state: DungeonMasterState) -> dict:
        """🏗️ Run the npc_builder graph one conversational turn for the
        NPC currently at the head of the build queue."""
        intro = state.build_queue[0]
        transcript = list(state.build_transcript)

        if not transcript:
            logger.info(f"🏗️ Opening build negotiation for NPC '{intro.name}'")
            transcript = [HumanMessage(content=(
                f"Design an NPC named exactly '{intro.name}'. "
                f"The name passed to create_character MUST be exactly '{intro.name}'.\n\n"
                f"Build instructions:\n{intro.build_instructions}"
            ))]

        builder_graph = spawn_npc_builder(campaign.lore_world)
        try:
            result = await builder_graph.ainvoke({"messages": transcript})
            delta = result["messages"][len(transcript):]
        except Exception:
            logger.exception(f"💥 NPC builder graph failed for '{intro.name}'")
            delta = []

        created = any(isinstance(m, ToolMessage) and m.name == "create_character" for m in delta)
        if created:
            logger.info(f"✅ Builder persisted '{intro.name}' via create_character")

        return {"messages": [], "build_transcript": transcript + delta, "build_created": created}

    async def npc_build_reviewer(state: DungeonMasterState) -> dict:
        """⚖️ The DM argues back: answers the builder's questions,
        critiques the draft card, or approves it for persistence."""
        intro = state.build_queue[0]
        rounds = state.build_rounds + 1
        call_now = (
            f"Call create_character now with the name exactly '{intro.name}' and the full W++ card."
        )

        if rounds >= MAX_BUILD_ROUNDS:
            logger.warning(f"⏰ Build negotiation for '{intro.name}' hit round {rounds}, forcing approval")
            reply = f"We are out of time -- the players are waiting. The card is approved as-is. {call_now}"
        else:
            transcript_text = "\n\n".join(
                f"{'DM' if isinstance(m, HumanMessage) else 'BUILDER'}: {m.content}"
                for m in state.build_transcript
                if isinstance(m, (HumanMessage, AIMessage)) and m.content
            )
            prompt = await dm_npc_reviewer_prompt_template.ainvoke({
                "npc_name": intro.name,
                "build_instructions": intro.build_instructions,
                "negotiation_transcript": transcript_text,
            })
            review: BuildReview = await dm_review_llm.ainvoke(prompt)
            logger.info(
                f"⚖️ DM review round {rounds} for '{intro.name}': "
                f"approved={review.approved}, feedback={review.feedback[:120]}"
            )
            reply = f"{review.feedback}\n\nApproved. {call_now}" if review.approved else review.feedback

        return {
            "build_transcript": [*state.build_transcript, HumanMessage(content=reply)],
            "build_rounds": rounds,
        }

    async def npc_registrar(state: DungeonMasterState) -> dict:
        """🎭 Register the freshly built NPC into the scene and advance the build queue."""
        intro = state.build_queue[0]

        if state.build_created:
            character = db_session.query(CharacterModel).filter(
                CharacterModel.name == intro.name
            ).first()
            if character is None:
                logger.error(f"❌ Builder reported success but '{intro.name}' not in DB")
            else:
                conversation.add_character(character)
                conversation._npcs_introduced = True
                logger.info(f"🎭 NPC '{intro.name}' introduced to scene")
        else:
            logger.error(f"❌ Build negotiation for '{intro.name}' ended without persistence, skipping")

        return {
            "messages": [],
            "build_queue": state.build_queue[1:],
            "build_transcript": [],
            "build_rounds": 0,
            "build_created": False,
        }

    async def _narrate(notes: str, state: DungeonMasterState) -> AIMessage:
        """Expand DM narration notes into full Narrator prose."""
        prompt = await dm_narrator_prompt_template.ainvoke({
            "narration_notes": notes,
            "location": conversation.location,
            "story_background": conversation.story_background,
            "messages": [*conversation.message_buffer, *state.messages],
        })
        prefix = f"{NARRATOR_NAME}: "
        prompt.messages.append(AIMessage(content=prefix))

        response = await dm_narrator_model.ainvoke(prompt)
        content = response.content.strip()
        while content.startswith(prefix):
            content = content[len(prefix):].lstrip()
        return AIMessage(content=f"{prefix}{content}", name=NARRATOR_NAME, id=str(uuid4()))

    async def dm_narrator_opening(state: DungeonMasterState) -> dict:
        """Expand opening narration notes into full prose."""
        plan = state.plan
        if not plan:
            return {"messages": []}

        notes: list[str] = []
        # Only narrate the action outcome when no NPC is around to convey it.
        if plan.action_outcome and not plan.responding_npcs:
            notes.append(f"Action outcome: {plan.action_outcome}")
        if plan.time_location_update:
            notes.append(f"Scene change: {plan.time_location_update}")
        if plan.opening_narration:
            notes.append(f"Opening narration: {plan.opening_narration}")
        notes.extend(f"New character enters: {i.entrance_narration}" for i in plan.npcs_to_introduce)
        if not notes:
            return {"messages": []}

        msg = await _narrate("\n".join(notes), state)
        logger.info(f"📜 Opening narration: {msg.content[:120]}...")
        return {"messages": [msg]}

    async def npc_executor(state: DungeonMasterState) -> dict:
        """Dynamically build and run each selected NPC in the DM's order."""
        plan = state.plan
        if not plan or not plan.responding_npcs:
            return {"messages": []}

        all_messages: list[AnyMessage] = []
        for directive in plan.responding_npcs:
            character = next((c for c in conversation.characters if c.name == directive.name), None)
            if character is None:
                logger.warning(f"⚠️ NPC '{directive.name}' not found in conversation characters")
                continue

            npc_graph = spawn_npc_directed(character, conversation, directive)
            input_messages = [*state.messages, *all_messages]
            try:
                if sio is not None and sid is not None:
                    delta = await _stream_npc_to_socket(npc_graph, input_messages, character.name, sio, sid)
                else:
                    result = await npc_graph.ainvoke({"messages": input_messages})
                    delta = result.get("messages", [])[len(input_messages):]
                all_messages.extend(delta)
                logger.info(f"🎭 {directive.name} produced {len(delta)} message(s)")
            except Exception:
                logger.exception(f"💥 NPC graph failed for '{directive.name}'")

        return {"messages": all_messages}

    async def dm_narrator_closing(state: DungeonMasterState) -> dict:
        """Expand closing narration notes into full prose."""
        if not state.plan or not state.plan.closing_narration:
            return {"messages": []}
        msg = await _narrate(state.plan.closing_narration, state)
        logger.info(f"📜 Closing narration: {msg.content[:120]}...")
        return {"messages": [msg]}

    async def consequence_tracker(state: DungeonMasterState) -> dict:
        """Persist world events and DM secrets to Graphiti, update location, dismiss NPCs."""
        plan = state.plan
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

        # for dismissed in plan.npcs_to_dismiss:
        #     character = next((c for c in conversation.characters if c.name == dismissed), None)
        #     if character is None:
        #         logger.warning(f"⚠️ Cannot dismiss '{dismissed}': not in the scene")
        #     else:
        #         conversation.remove_character(character)

        return {"messages": []}

    async def persist_messages(state: DungeonMasterState) -> dict:
        """Write all messages from this turn to the DB and message buffer."""
        for message in state.messages:
            message.id = message.id or str(uuid4())
            if isinstance(message, HumanMessage):
                message.name = player.name
            conversation.add_message(message.type, message.content, message.name, _id=UUID(message.id))

        conversation.message_buffer.extend(state.messages)
        ids = [m.id for m in conversation.message_buffer]
        if (dupes := len(ids) - len(set(ids))):
            logger.error(f"👯‍♀️ {dupes} duplicate message IDs detected")

        return {"messages": []}

    graph = StateGraph(DungeonMasterState)
    for node in (
        context_loader, dm_planner, npc_builder_caller, npc_build_reviewer, npc_registrar,
        dm_narrator_opening, npc_executor, dm_narrator_closing, consequence_tracker,
    ):
        graph.add_node(node.__name__, node)
    graph.add_node("persist_messages", persist_messages, defer=True)

    scene_targets = ["npc_builder_caller", "dm_narrator_opening", "npc_executor"]
    graph.add_edge(START, "context_loader")
    graph.add_edge("context_loader", "dm_planner")
    graph.add_conditional_edges("dm_planner", after_plan_or_registrar, scene_targets)
    graph.add_conditional_edges("npc_builder_caller", after_builder, ["npc_build_reviewer", "npc_registrar"])
    graph.add_edge("npc_build_reviewer", "npc_builder_caller")
    graph.add_conditional_edges("npc_registrar", after_plan_or_registrar, scene_targets)
    graph.add_edge("dm_narrator_opening", "npc_executor")
    graph.add_conditional_edges("npc_executor", after_npc_executor)
    graph.add_edge("dm_narrator_closing", "consequence_tracker")
    graph.add_edge("consequence_tracker", "persist_messages")
    graph.add_edge("persist_messages", END)

    return graph.compile(name=name)
