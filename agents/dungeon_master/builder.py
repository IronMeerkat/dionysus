"""The DM <-> NPC-builder negotiation loop: draft, argue, approve, register."""
from logging import getLogger

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agents.dungeon_master.context import DMContext
from agents.dungeon_master.schemas import BuildReview, DungeonMasterState
from agents.tool_agent import spawn_npc_builder
from database.models import Character as CharacterModel
from database.postgres_connection import session as db_session
from tools.participants import ensure_campaign_npc
from utils.llm_models import dm_planner_model
from utils.prompts import dm_npc_reviewer_prompt_template

logger = getLogger(__name__)

# Max DM<->builder argument rounds per NPC before the DM forces approval.
MAX_BUILD_ROUNDS = 3


def make_builder_nodes(ctx: DMContext) -> dict:
    """Build the three negotiation-loop nodes sharing the same context."""
    dm_review_llm = dm_planner_model.with_structured_output(BuildReview, strict=True)

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

        builder_graph = spawn_npc_builder(ctx.campaign.lore_world)
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
                ctx.conversation.add_character(character)
                ctx.conversation._npcs_introduced = True
                ensure_campaign_npc(ctx.campaign.id, character.id)
                logger.info(f"🎭 NPC '{intro.name}' introduced to scene (state row ensured)")
        else:
            logger.error(f"❌ Build negotiation for '{intro.name}' ended without persistence, skipping")

        return {
            "messages": [],
            "build_queue": state.build_queue[1:],
            "build_transcript": [],
            "build_rounds": 0,
            "build_created": False,
        }

    return {
        "npc_builder_caller": npc_builder_caller,
        "npc_build_reviewer": npc_build_reviewer,
        "npc_registrar": npc_registrar,
    }


def after_builder(state: DungeonMasterState) -> str:
    if state.build_created:
        return "npc_registrar"
    if state.build_rounds >= MAX_BUILD_ROUNDS:
        logger.error("🛑 Builder never persisted the NPC despite forced approval, giving up")
        return "npc_registrar"
    return "npc_build_reviewer"
