"""The DM's narrative voice: expand plan notes into Narrator prose."""
from logging import getLogger
from uuid import uuid4

from langchain_core.messages import AIMessage

from agents.dungeon_master.context import DMContext
from agents.dungeon_master.schemas import NARRATOR_NAME, DungeonMasterState
from utils.llm_models import dm_narrator_model
from utils.prompts import dm_narrator_prompt_template

logger = getLogger(__name__)


def make_narrator_nodes(ctx: DMContext) -> dict:
    async def _narrate(notes: str, state: DungeonMasterState) -> AIMessage:
        """Expand DM narration notes into full Narrator prose."""
        prompt = await dm_narrator_prompt_template.ainvoke({
            "narration_notes": notes,
            "location": ctx.location,
            "story_background": ctx.story_background,
            "messages": ctx.combined_messages(state),
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

    async def dm_narrator_closing(state: DungeonMasterState) -> dict:
        """Expand closing narration notes into full prose."""
        if not state.plan or not state.plan.closing_narration:
            return {"messages": []}
        msg = await _narrate(state.plan.closing_narration, state)
        logger.info(f"📜 Closing narration: {msg.content[:120]}...")
        return {"messages": [msg]}

    return {
        "dm_narrator_opening": dm_narrator_opening,
        "dm_narrator_closing": dm_narrator_closing,
    }
