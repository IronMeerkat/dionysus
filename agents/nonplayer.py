import asyncio
import operator
import re
from logging import getLogger
from typing import TYPE_CHECKING, Annotated
from uuid import uuid4

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from hephaestus.helpers import Oligaton
from hephaestus.settings import settings

from database.graphiti_utils import (
    fire_and_forget,
    load_information,
    make_group_id,
    make_memory_group_id,
    process_and_save_memory,
)
from database.models import Character as CharacterModel
from database.models.conversation import Conversation
from tools.participants import render_npc_state, render_player_state
from utils.llm_models import npc_emotions, npc_narration, npc_thoughts
from utils.prompts import (
    character_episodic_memory,
    emotions_prompt_template,
    narrator_prompt_template,
    plan_prompt_template,
)

if TYPE_CHECKING:
    from agents.dungeon_master import NPCDirective

info_limits = settings.graphiti.information_limits
logger = getLogger(__name__)


class EmotionalState(BaseModel, metaclass=Oligaton):
    love: int = Field(default=0, ge=-20, le=20, description="Intensity of affectionate attachment.")
    hate: int = Field(default=0, ge=-20, le=20, description="Intensity of hostile aversion.")
    fear: int = Field(default=0, ge=-20, le=20, description="Intensity of perceived threat or dread.")
    joy: int = Field(default=0, ge=-20, le=20, description="Intensity of happiness or delight.")
    sadness: int = Field(default=0, ge=-20, le=20, description="Intensity of sorrow or grief.")
    hope: int = Field(default=0, ge=-20, le=20, description="Intensity of positive expectation for outcomes.")


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

    other_characters = "\n\n\n".join(
        f"**{c.name}**:\n{c.description}"
        for c in conversation.characters
        if c.id != character.id
    )
    other_speakers = [c.name for c in conversation.characters if c.id != character.id]
    other_speakers.append(conversation.player.name)

    emotional_state_model = npc_emotions.with_structured_output(EmotionalState.model_json_schema(), strict=True)
    emotional_state = EmotionalState(_key=character.name)

    withheld_block = "".join(f"\n- {fact}" for fact in directive.withheld_info)
    if withheld_block:
        withheld_block = "\n[INFORMATION YOU DO NOT KNOW - never reference these facts]" + withheld_block

    class NPCState(BaseModel):
        messages: Annotated[list[AnyMessage], operator.add]
        thoughts: str = Field(default="")
        lore: str = Field(default="")
        memories: str = Field(default="")
        self_state: str = Field(default="", description="This NPC's live mechanical state, rendered prompt-ready.")
        player_state: str = Field(default="", description="The player character's live mechanical state, rendered prompt-ready.")

        @property
        def combined_messages(self) -> list[AnyMessage]:
            combo = [*conversation.message_buffer, *self.messages]
            return combo[-min(settings.context_size, len(combo)):]

        @property
        def emotional_state(self) -> str:
            raw = emotional_state.model_dump(exclude_unset=True)
            return "\n".join(f"{k}: {v}" for k, v in raw.items())

        @property
        def combined_dump(self) -> dict:
            return {
                "name": character.name,
                "description": character.description + withheld_block,
                "other_characters": other_characters,
                "player": conversation.player.description,
                "player_name": conversation.player.name,
                "location": conversation.campaign.location,
                "story_background": conversation.campaign.story_background,
                "messages": self.combined_messages,
                "emotional_state": self.emotional_state,
                "dm_guidance": directive.guidance,
                **self.model_dump(exclude={"messages"}),
            }

    async def context_loader(state: NPCState) -> dict:
        last_human = next((m for m in reversed(state.messages) if isinstance(m, HumanMessage)), None)
        query = last_human.content if last_human else character.name
        lore, memories = await asyncio.gather(
            load_information(
                query=query,
                group_ids=[make_group_id("lore", conversation.campaign.lore_world)],
                limit=info_limits.lore,
            ),
            load_information(
                query=query,
                group_ids=[make_memory_group_id(conversation.campaign.id, character.name)],
                limit=info_limits.memories,
            ),
        )
        self_state = render_npc_state(conversation.campaign.id, character.id, character.name)
        player_state = render_player_state(conversation.campaign.id, conversation.player.id)
        return {
            "lore": lore,
            "memories": memories,
            "self_state": self_state,
            "player_state": player_state,
            "messages": [],
        }

    async def emotion_updater(state: NPCState) -> dict:
        prompt = await emotions_prompt_template.ainvoke(state.combined_dump)
        delta = await emotional_state_model.ainvoke(prompt)
        logger.info(f"💖 Emotion delta for {character.name}: {delta}")

        for field_name, value in delta.items():
            current = getattr(emotional_state, field_name)
            setattr(emotional_state, field_name, max(-20, min(20, current + value)))
        return {"messages": []}

    async def planner(state: NPCState) -> dict:
        prompt = await plan_prompt_template.ainvoke(state.combined_dump)
        thoughts = await npc_thoughts.ainvoke(prompt)
        if thoughts.content is None:
            logger.warning(f"🧠 {character.name} planner returned None")

        tagged = f"## {character.name} THOUGHTS:\n{thoughts.content}"
        logger.info(f"🧠 {character.name}: {tagged[:200]}...")
        return {"thoughts": tagged, "messages": []}

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
        fire_and_forget(process_and_save_memory(
            messages=state.combined_messages,
            group_id=make_memory_group_id(conversation.campaign.id, character.name),
            source_description=f"session:{conversation.campaign.lore_world}",
            perspective=character_episodic_memory.compile(name=character.name, description=character.description),
            character_name=character.name,
            character_description=character.description,
        ))
        return {"messages": [response]}

    graph = StateGraph(NPCState)
    for node in (context_loader, emotion_updater, planner, npc_narrator):
        graph.add_node(node.__name__, node)

    graph.add_edge(START, "context_loader")
    graph.add_edge("context_loader", "emotion_updater")
    graph.add_edge("emotion_updater", "planner")
    graph.add_edge("planner", "npc_narrator")
    graph.add_edge("npc_narrator", END)

    return graph.compile(name=character.name)
