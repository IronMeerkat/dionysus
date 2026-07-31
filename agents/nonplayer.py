import asyncio
import operator
import re
from logging import getLogger
from typing import TYPE_CHECKING, Annotated
from uuid import uuid4

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from hephaestus.settings import settings

from database.models import Campaign, Character as CharacterModel, CharacterMemory
from database.models.conversation import Conversation
from tools.participants import render_participant_state
from tools.status_effects import character_sheet_by_id
from utils.llm_models import npc_narration
from utils.prompts import narrator_prompt_template
from utils.tasks import fire_and_forget

if TYPE_CHECKING:
    from agents.dungeon_master import NPCDirective

logger = getLogger(__name__)


def strip_speaker_prefix(raw: str, name: str) -> str:
    """Remove any leading '{name}:' speaker labels (repeated, any casing) from narration."""
    pattern = re.compile(
        rf"^\s*\**\s*{re.escape(name)}\s*\**\s*:(?:\s*\*+(?=\s|$))?\s*",
        re.IGNORECASE,
    )
    content = (raw or "").strip()
    while (match := pattern.match(content)):
        content = content[match.end():].strip()
    return content


def truncate_foreign_turns(content: str, other_speakers: list[str]) -> tuple[str, bool]:
    """Cut narration at the first line that starts another participant's turn.

    Catches the failure mode where the model 'completes the transcript' instead of
    writing only its own turn — e.g. replaying the player's message as ``Ariel: ...``
    or continuing into ``Narrator: ...`` after its own line.
    """
    if not other_speakers or not content:
        return content, False
    names = "|".join(re.escape(n) for n in other_speakers if n)
    pattern = re.compile(rf"^\s*\**\s*(?:{names})\s*\**\s*:", re.IGNORECASE | re.MULTILINE)
    match = pattern.search(content)
    if match is None:
        return content, False
    return content[:match.start()].strip(), True


async def narrate_with_retry(
    prompt,
    name: str,
    other_speakers: list[str] | None = None,
    max_attempts: int = 3,
) -> tuple[AIMessage | None, str]:
    """Invoke the narration model, retrying on empty, name-only, or ventriloquized replies.

    The narrator prompt ends with a prefilled ``AIMessage("{name}: ")``; some models
    occasionally continue it by just re-emitting the name and stopping, or by speaking
    a turn for another participant (including the player). Foreign turns are truncated;
    if nothing of the NPC's own remains, the call is retried with a corrective system
    nudge inserted right before the prefill.
    """
    other_speakers = [*(other_speakers or []), "Narrator"]
    messages = list(prompt.messages)
    response = None
    for attempt in range(1, max_attempts + 1):
        response = await npc_narration.ainvoke(messages)
        content = strip_speaker_prefix(response.content, name)
        content, truncated = truncate_foreign_turns(content, other_speakers)
        if truncated:
            logger.warning(
                f"🎭 {name} tried to speak for another participant; truncated their turn "
                f"(attempt {attempt}/{max_attempts}): {response.content[:120]!r}"
            )
        if content:
            if attempt > 1:
                logger.info(f"🎭 {name} produced narration on attempt {attempt}")
            return response, content
        logger.warning(
            f"🎭 {name} returned an empty/name-only/ventriloquized narration "
            f"(attempt {attempt}/{max_attempts}): {response.content[:200]!r}"
        )
        nudge = SystemMessage(content=(
            f"Your previous reply was invalid: it was empty, contained only a speaker "
            f"label, or spoke a turn on behalf of another participant "
            f"({', '.join(other_speakers)}). You must now write {name}'s OWN turn only: "
            f"at least one full sentence of dialogue or *action*, fully in character as "
            f"{name}. Never write a line that begins with another participant's name, "
            f"and never repeat earlier messages from the conversation."
        ))
        messages = [*messages[:-1], nudge, messages[-1]]
    logger.error(f"💀 {name} failed to produce narration after {max_attempts} attempts")
    return response, ""


def spawn_npc_directed(
    character: CharacterModel,
    conversation: Conversation,
    directive: "NPCDirective",
) -> StateGraph:
    """Build an NPC graph that honors a DM directive.

    The ``directive`` provides ``.guidance`` (what to focus on) and
    ``.withheld_info`` (facts to avoid revealing). The DM planner has
    already decided this NPC responds this turn, so there is no veto.
    """

    # Sheets/location/background are fetched fresh per spawn (the conversation
    # is a detached snapshot; its roster supplies ids and names only).
    campaign = Campaign.get(id=conversation.campaign_id)
    other_characters = "\n\n\n".join(
        f"**{c.name}**:\n{character_sheet_by_id(c.id)}"
        for c in conversation.characters
        if c.id != character.id
    )
    other_speakers = [c.name for c in conversation.characters if c.id != character.id]
    other_speakers.append(conversation.player.name)

    withheld_block = "".join(f"\n- {fact}" for fact in directive.withheld_info)
    if withheld_block:
        withheld_block = "\n[INFORMATION YOU DO NOT KNOW - never reference these facts]" + withheld_block

    class NPCState(BaseModel):
        messages: Annotated[list[AnyMessage], operator.add]
        lore: str = Field(default="")
        memories: str = Field(default="")
        self_state: str = Field(default="", description="This NPC's live mechanical state, rendered prompt-ready.")
        player_state: str = Field(default="", description="The player character's live mechanical state, rendered prompt-ready.")

        @property
        def combined_messages(self) -> list[AnyMessage]:
            combo = [*conversation.message_buffer, *self.messages]
            return combo[-min(settings.context_size, len(combo)):]

        @property
        def combined_dump(self) -> dict:
            return {
                "name": character.name,
                "description": character_sheet_by_id(character.id) + withheld_block,
                "other_characters": other_characters,
                "player": character_sheet_by_id(conversation.player_id),
                "player_name": conversation.player.name,
                "location": campaign.location if campaign else "",
                "story_background": (campaign.story_background if campaign else "") or "",
                "messages": self.combined_messages,
                "dm_guidance": directive.guidance,
                **self.model_dump(exclude={"messages"}),
            }

    async def context_loader(state: NPCState) -> dict:
        """🧠 Load this NPC's memories (pgvector recall) and live participant
        states. Lore arrives in the initial state from the DM's retriever."""
        last_human = next((m for m in reversed(state.messages) if isinstance(m, HumanMessage)), None)
        query = last_human.content if last_human else character.name

        def _participant_states() -> tuple[str, str]:
            return (
                render_participant_state(conversation.campaign_id, character.id, character.name),
                render_participant_state(conversation.campaign_id, conversation.player.id),
            )

        memories, (self_state, player_state) = await asyncio.gather(
            CharacterMemory.recall(conversation.campaign_id, character.id, query),
            asyncio.to_thread(_participant_states),
        )
        return {
            "memories": memories,
            "self_state": self_state,
            "player_state": player_state,
            "messages": [],
        }

    async def npc_narrator(state: NPCState) -> dict:
        prompt = await narrator_prompt_template.ainvoke(state.combined_dump)
        prefix = f"{character.name}: "
        prompt.messages.append(AIMessage(content=prefix))

        response, content = await narrate_with_retry(prompt, character.name, other_speakers)
        if not content:
            logger.error(f"💀 {character.name} skipping turn: no usable narration produced")
            return {"messages": []}

        response.content = prefix + content
        response.name = character.name
        response.id = str(uuid4())
        fire_and_forget(CharacterMemory.process_and_save(
            messages=state.combined_messages,
            campaign_id=conversation.campaign_id,
            character_id=character.id,
            character_name=character.name,
            character_description=character_sheet_by_id(character.id),
        ))
        return {"messages": [response]}

    graph = StateGraph(NPCState)
    for node in (context_loader, npc_narrator):
        graph.add_node(node.__name__, node)

    graph.add_edge(START, "context_loader")
    graph.add_edge("context_loader", "npc_narrator")
    graph.add_edge("npc_narrator", END)

    return graph.compile(name=character.name)
