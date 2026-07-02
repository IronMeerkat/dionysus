"""Intent routing: classify the player's message and answer OOC questions."""
from logging import getLogger
from uuid import uuid4

from langchain_core.messages import AIMessage

from agents.dungeon_master.context import DMContext
from agents.dungeon_master.schemas import NARRATOR_NAME, DungeonMasterState, IntentReading
from utils.llm_models import dm_intent_model, dm_ooc_model
from utils.prompts import dm_intent_router_prompt_template, dm_ooc_responder_prompt_template

logger = getLogger(__name__)

# Intent types that bypass the story pipeline and get a direct DM answer.
OOC_INTENTS = frozenset({"ooc_question", "rules_question", "meta"})

# How much recent conversation the cheap classifier hops get to see.
ROUTER_CONTEXT_WINDOW = 12


def make_intent_router(ctx: DMContext):
    intent_llm = dm_intent_model.with_structured_output(IntentReading, strict=True)

    async def intent_router(state: DungeonMasterState) -> dict:
        """🧭 Classify the player's latest message: what do they want this turn?"""
        prompt = await dm_intent_router_prompt_template.ainvoke({
            "player_name": ctx.player.name,
            "location": ctx.location,
            "world_clock": ctx.world_clock,
            "active_npcs": ctx.npc_names,
            "player_state": state.player_state,
            "messages": ctx.combined_messages(state, limit=ROUTER_CONTEXT_WINDOW),
        })
        try:
            reading: IntentReading = await intent_llm.ainvoke(prompt)
        except Exception:
            logger.exception("💥 Intent router failed, defaulting to in-character dialogue")
            reading = IntentReading(
                intent_type="dialogue",
                scene_mode="social",
                needs_adjudication=False,
                summary=ctx.last_human_query(state, fallback="(unreadable intent)")[:200],
            )
        logger.info(
            f"🧭 Intent: {reading.intent_type} / {reading.scene_mode} "
            f"(adjudicate={reading.needs_adjudication}) -- {reading.summary[:120]}"
        )
        return {"messages": [], "intent": reading}

    return intent_router


def route_intent(state: DungeonMasterState) -> str:
    if state.intent and state.intent.intent_type in OOC_INTENTS:
        logger.info("🎙️ OOC short-circuit: answering the player directly, no story turn")
        return "ooc_responder"
    return "rules_referee"


def make_ooc_responder(ctx: DMContext):
    async def ooc_responder(state: DungeonMasterState) -> dict:
        """🎙️ Answer an out-of-character / rules / meta question in the DM voice.

        Speaks as the Narrator so the frontend needs no new speaker concept.
        Never advances the story and never touches the secrets group.
        """
        prompt = await dm_ooc_responder_prompt_template.ainvoke({
            "lore": state.lore,
            "world_events": state.world_events,
            "open_threads": state.open_threads,
            "location": ctx.location,
            "world_clock": ctx.world_clock,
            "story_background": ctx.story_background,
            "player_name": ctx.player.name,
            "messages": ctx.combined_messages(state),
        })
        prefix = f"{NARRATOR_NAME}: "
        prompt.messages.append(AIMessage(content=prefix))

        try:
            response = await dm_ooc_model.ainvoke(prompt)
        except Exception:
            logger.exception("💥 OOC responder failed")
            return {"messages": []}

        content = (response.content or "").strip()
        while content.startswith(prefix):
            content = content[len(prefix):].lstrip()
        if not content:
            logger.error("💀 OOC responder produced an empty answer, skipping")
            return {"messages": []}

        logger.info(f"🎙️ OOC answer: {content[:120]}...")
        msg = AIMessage(content=f"{prefix}{content}", name=NARRATOR_NAME, id=str(uuid4()))
        return {"messages": [msg]}

    return ooc_responder
