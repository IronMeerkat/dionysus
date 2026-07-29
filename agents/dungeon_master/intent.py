"""Intent routing: OOC branch predicate and the out-of-character responder.

The intent classifier itself lives in ``agents.dungeon_master.classifiers``
(it is skill-driven); this module keeps the routing predicate and the OOC
answer node.
"""
from logging import getLogger
from uuid import uuid4

from langchain_core.messages import AIMessage

from agents.dungeon_master.context import DMContext
from agents.dungeon_master.schemas import NARRATOR_NAME, DungeonMasterState
from utils.llm_models import dm_ooc_model
from utils.prompts import dm_ooc_responder_prompt_template

logger = getLogger(__name__)

# Intent types that bypass the story pipeline and get a direct DM answer.
OOC_INTENTS = frozenset({"ooc_question", "rules_question", "meta"})


def route_intent(state: DungeonMasterState) -> str:
    if state.intent and state.intent.intent_type in OOC_INTENTS:
        logger.info("🎙️ OOC short-circuit: answering the player directly, no story turn")
        return "ooc_responder"
    return "dm_planner"


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
