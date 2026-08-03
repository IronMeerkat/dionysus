"""Intent routing: the zero-LLM OOC router node and the OOC responder.

OOC detection is regex first (explicit markers), then a nearest-neighbor
vote over seeded exemplar embeddings reusing the turn's query vector.
Anything not confidently OOC takes the story path -- the planner reads the
player's message itself and needs no classified intent.
"""
import asyncio
import re
from logging import getLogger
from typing import Literal
from uuid import uuid4

from langchain_core.messages import AIMessage

from agents.dungeon_master.context import DMContext
from agents.dungeon_master.schemas import NARRATOR_NAME, DungeonMasterState
from database.models.routing import LABEL_OOC, LABEL_STORY, RoutingExemplar
from hephaestus.settings import settings
from utils.llm_models import dm_ooc_model
from utils.prompts import dm_ooc_responder_prompt_template

logger = getLogger(__name__)

# Explicit out-of-character markers: a leading "OOC:"/"((", or the whole
# message wrapped in parentheses.
_OOC_MARKERS = re.compile(r"^\s*(?:\(\s*)?ooc[\s:)\]]|^\s*\(\(", re.IGNORECASE)
_WRAPPED_IN_PARENS = re.compile(r"^\s*\(+.*?\)+\s*$", re.DOTALL)


def _regex_ooc(text: str) -> bool:
    return bool(_OOC_MARKERS.match(text) or _WRAPPED_IN_PARENS.match(text))


async def route_by_exemplars(vector: list[float]) -> Literal["ooc", "story"] | None:
    """🏷️ Route the player's message by majority vote over the nearest
    seeded exemplars -- no LLM call.

    Confident (returns a label) only when the nearest exemplar is within
    ``tau_confident`` (L2) AND the label margin among the top-k exceeds
    ``tau_margin``; otherwise returns None (unsure). Fail-secure: any
    search failure also returns None.
    """
    cfg = settings.memory.routing
    try:
        neighbors = await asyncio.to_thread(RoutingExemplar.nearest, vector, cfg.exemplars_top_k)
    except Exception:
        logger.exception("💥 Exemplar routing search failed; treating as unsure")
        return None

    if not neighbors:
        logger.warning("⚠️ No routing exemplars seeded; treating as unsure")
        return None

    ooc_votes = sum(1 for exemplar, _ in neighbors if exemplar.label == LABEL_OOC)
    story_votes = len(neighbors) - ooc_votes
    if ooc_votes == story_votes:
        logger.info(f"🏷️ Exemplar vote tied {ooc_votes}:{story_votes}; unsure")
        return None

    majority = LABEL_OOC if ooc_votes > story_votes else LABEL_STORY
    nearest_distance = neighbors[0][1]
    margin = abs(ooc_votes - story_votes) / len(neighbors)
    confident = nearest_distance <= cfg.tau_confident and margin >= cfg.tau_margin
    logger.info(
        f"🏷️ Exemplar route: {majority} {max(ooc_votes, story_votes)}:{min(ooc_votes, story_votes)} "
        f"(nearest={nearest_distance:.3f}/{cfg.tau_confident}, margin={margin:.2f}/{cfg.tau_margin}) "
        f"-> {'confident' if confident else 'unsure'}"
    )
    return majority if confident else None


def make_intent_router(ctx: DMContext):
    async def intent_router(state: DungeonMasterState) -> dict:
        """🧭 Mark the turn OOC or story -- regex first, exemplar vote second,
        no LLM call. Unsure always means story: the worst case is the DM
        answering a meta question in-fiction, never a story move ignored.
        """
        latest = next((m for m in reversed(state.messages) if m.type == "human"), None)
        text = (latest.content if latest else "").strip()
        if text and _regex_ooc(text):
            logger.info("🧭 Explicit OOC marker; short-circuiting to the OOC responder")
            return {"messages": [], "ooc": True}
        if state.query_vector is not None:
            if await route_by_exemplars(state.query_vector) == "ooc":
                logger.info("🧭 Confident exemplar OOC vote; short-circuiting to the OOC responder")
                return {"messages": [], "ooc": True}
        return {"messages": [], "ooc": False}

    return intent_router


def route_intent(state: DungeonMasterState) -> str:
    if state.ooc:
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
