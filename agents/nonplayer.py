import asyncio
import re
from logging import getLogger
from typing import TYPE_CHECKING, Annotated
from uuid import uuid4

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

from hephaestus.settings import settings
from hephaestus.agent_architectures.retry import nudged_agent

from database.models import Campaign, Character as CharacterModel, CharacterMemory
from database.models.conversation import Conversation
from tools.participants import render_participant_state
from tools.status_effects import character_sheet_by_id
from utils.llm_models import npc_narration
from utils.prompts import narrator_prompt_template

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


def spawn_npc_directed(
    character: CharacterModel,
    conversation: Conversation,
    directive: "NPCDirective",
    query_vector: list[float] | None = None,
) -> StateGraph:
    """Build an NPC graph that honors a DM directive.

    The ``directive`` provides ``.guidance`` (what to focus on) and
    ``.withheld_info`` (facts to avoid revealing). The DM planner has
    already decided this NPC responds this turn, so there is no veto.

    ``query_vector`` is the turn's precomputed player-message embedding;
    when present the memory recall reuses it instead of re-embedding.
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
    other_speakers.extend([conversation.player.name, "Narrator"])
    # Server-side stop sequences end generation the moment the model starts another
    # participant's turn; nudged_agent below is the safety net for what slips through.
    stop = [f"\n{n}:" for n in other_speakers]
    foreign_turn = re.compile(
        rf"^\s*\**\s*(?:{'|'.join(map(re.escape, other_speakers))})\s*\**\s*:",
        re.IGNORECASE | re.MULTILINE,
    )
    nudge_text = (
        f"Your previous reply was invalid: it was empty, contained only a speaker label, or "
        f"spoke a turn on behalf of another participant ({', '.join(other_speakers)}). "
        f"You must now write {character.name}'s OWN turn only: at least one full sentence of "
        f"dialogue or *action*, fully in character as {character.name}. Never write a line "
        f"that begins with another participant's name, and never repeat earlier messages "
        f"from the conversation."
    )

    def is_valid_turn(message: AIMessage) -> bool:
        """Non-empty after the speaker label, and no ventriloquized lines for others."""
        body = strip_speaker_prefix(message.content, character.name)
        return bool(body) and not foreign_turn.search(body)

    withheld_block = "".join(f"\n- {fact}" for fact in directive.withheld_info)
    if withheld_block:
        withheld_block = "\n[INFORMATION YOU DO NOT KNOW - never reference these facts]" + withheld_block

    class NPCState(BaseModel):
        messages: Annotated[list[AnyMessage], add_messages]  # add_messages: nudged_agent removes messages by id
        lore: str = Field(default="")
        memories: str = Field(default="")
        self_state: str = Field(default="", description="This NPC's live mechanical state, rendered prompt-ready.")
        player_state: str = Field(default="", description="The player character's live mechanical state, rendered prompt-ready.")
        # Turn-level player-message embedding from the DM state_loader;
        # reused for memory recall so each NPC skips its own embedder call.
        query_vector: list[float] | None = Field(default=None, exclude=True)

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
                **self.model_dump(exclude={"messages", "query_vector"}),
            }

    async def context_loader(state: NPCState) -> dict:
        """🧠 Load this NPC's memories (pgvector recall) and live participant
        states. Lore and the turn's query vector arrive in the initial state
        from the DM; the vector is reused for recall when present."""
        def _participant_states() -> tuple[str, str]:
            return (
                render_participant_state(conversation.campaign_id, character.id, character.name),
                render_participant_state(conversation.campaign_id, conversation.player.id),
            )

        if state.query_vector is not None:
            memories_coro = CharacterMemory.recall_by_vector(
                conversation.campaign_id, character.id, state.query_vector
            )
        else:
            logger.warning(f"⚠️ {character.name}: no turn query vector, embedding for memory recall directly")
            last_human = next((m for m in reversed(state.messages) if isinstance(m, HumanMessage)), None)
            query = last_human.content if last_human else character.name
            memories_coro = CharacterMemory.recall(conversation.campaign_id, character.id, query)

        memories, (self_state, player_state) = await asyncio.gather(
            memories_coro,
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

        response = await npc_narration.ainvoke(prompt.messages, stop=stop)
        response.content = prefix + strip_speaker_prefix(response.content, character.name)
        response.name = character.name
        response.id = str(uuid4())
        # No per-turn memory extraction: lasting memories are distilled once
        # per scene by the merged scene epilogue (character_memories field).
        return {"messages": [response]}

    # Narrator is its own graph so retries re-run only the model call, not memory recall.
    narrator = StateGraph(NPCState)
    narrator.add_node(npc_narrator)
    narrator.add_edge(START, "npc_narrator")
    narrator.add_edge("npc_narrator", END)

    narrator_agent = narrator.compile(name=character.name)
    narrator_agent.state_schema = NPCState  # nudged_agent reads this off the agent to extend the state

    graph = StateGraph(NPCState)
    graph.add_node(context_loader)
    graph.add_node("narrator", nudged_agent(narrator_agent, is_valid_turn, nudge_text, max_retries=3))
    graph.add_edge(START, "context_loader")
    graph.add_edge("context_loader", "narrator")
    graph.add_edge("narrator", END)

    return graph.compile(name=character.name)
