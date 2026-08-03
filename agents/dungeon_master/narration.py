"""The DM's narrative voice: the planner writes player-ready prose, so most
narration costs zero calls -- the narrator model only weaves composite beats
(several things happening at once) into one passage."""
from logging import getLogger
from uuid import uuid4

from langchain_core.messages import AIMessage

from agents.dungeon_master.context import DMContext
from agents.dungeon_master.schemas import NARRATOR_NAME, DungeonMasterState
from utils.llm_models import dm_narrator_model
from utils.prompts import dm_narrator_prompt_template

logger = getLogger(__name__)

# How much recent conversation the narrator needs to match tone.
NARRATOR_CONTEXT_WINDOW = 8


def make_narrator_nodes(ctx: DMContext) -> dict:
    def _direct(prose: str) -> AIMessage:
        """Emit the planner's prose as the Narrator message -- no LLM call."""
        return AIMessage(content=f"{NARRATOR_NAME}: {prose.strip()}", name=NARRATOR_NAME, id=str(uuid4()))

    async def _narrate(notes: str, state: DungeonMasterState) -> AIMessage:
        """Weave several narration beats into one Narrator passage."""
        prompt = await dm_narrator_prompt_template.ainvoke({
            "narration_notes": notes,
            "location": ctx.location,
            "story_background": ctx.story_background,
            "messages": ctx.combined_messages(state, limit=NARRATOR_CONTEXT_WINDOW),
        })
        prefix = f"{NARRATOR_NAME}: "
        prompt.messages.append(AIMessage(content=prefix))

        response = await dm_narrator_model.ainvoke(prompt)
        content = response.content.strip()
        while content.startswith(prefix):
            content = content[len(prefix):].lstrip()
        return AIMessage(content=f"{prefix}{content}", name=NARRATOR_NAME, id=str(uuid4()))

    async def dm_narrator_opening(state: DungeonMasterState) -> dict:
        """Speak the plan's opening beats; only composite beats pay a call."""
        plan = state.plan
        if not plan:
            return {"messages": []}

        notes: list[tuple[str, str]] = []
        # Only narrate the action outcome when no NPC is around to convey it.
        if plan.action_outcome and not plan.responding_npcs:
            notes.append(("Action outcome", plan.action_outcome))
        if plan.time_location_update:
            notes.append(("Scene change", plan.time_location_update))
        if plan.opening_narration:
            notes.append(("Opening narration", plan.opening_narration))
        notes.extend(("New character enters", i.entrance_narration) for i in plan.npcs_to_introduce)
        if not notes:
            return {"messages": []}

        if len(notes) == 1:
            msg = _direct(notes[0][1])
        else:
            msg = await _narrate("\n".join(f"{label}: {text}" for label, text in notes), state)
        logger.info(f"📜 Opening narration: {msg.content[:120]}...")
        return {"messages": [msg]}

    async def dm_narrator_closing(state: DungeonMasterState) -> dict:
        """Speak the closing beat. Only NPC-less turns ever reach this node
        (the planner folds closing beats into the last NPC otherwise), so
        the planner's prose always goes out verbatim -- no LLM call."""
        if not state.plan or not state.plan.closing_narration:
            return {"messages": []}
        msg = _direct(state.plan.closing_narration)
        logger.info(f"📜 Closing narration: {msg.content[:120]}...")
        return {"messages": [msg]}

    return {
        "dm_narrator_opening": dm_narrator_opening,
        "dm_narrator_closing": dm_narrator_closing,
    }
