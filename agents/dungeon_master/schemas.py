"""Structured schemas and turn context for the DM supervisor."""
from __future__ import annotations

from dataclasses import dataclass, field
from logging import getLogger
from typing import TYPE_CHECKING, Any, Literal, TypeVar
from uuid import uuid4

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from pydantic import BaseModel, Field

from contracts.sinks import NullTurnSink
from contracts.turn_events import TurnSink

if TYPE_CHECKING:
    from database.models import Character as CharacterModel
    from database.models.conversation import Conversation

logger = getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

NARRATOR_NAME = "Narrator"
STREAM_MESSAGE_ID_KEY = "dionysus_message_id"
STREAM_SPEAKER_KEY = "dionysus_speaker"
NARRATOR_CONTEXT_WINDOW = 8


class AdjudicationRuling(BaseModel):
    """The rules referee's ruling on an uncertain player action (pre-dice)."""
    ruling: Literal["auto_success", "auto_failure", "roll", "impossible"] = Field(description=(
        "auto_success: nothing meaningfully opposes the action. auto_failure: cannot succeed as attempted, "
        "but something happens. roll: success and failure are both plausible. impossible: lacks the means."))
    check_label: str | None = Field(default=None, description="Check name in D&D style, e.g. 'Dexterity (Stealth)'. Only for ruling='roll'.")
    dc: int | None = Field(default=None, ge=5, le=30, description="Difficulty class (5-30). Only for ruling='roll'.")
    advantage: Literal["advantage", "normal", "disadvantage"] = Field(
        default="normal", description="Must reflect active status effects matching this check.")
    modifier: int = Field(default=0, ge=-10, le=10, description="Sum of applicable status effect roll_modifiers (0 when none apply).")
    applied_effects: list[str] = Field(default_factory=list, description="Names of status effects accounted for in advantage/modifier.")
    success_stakes: str = Field(description="What concretely happens on success.")
    failure_stakes: str = Field(description="What concretely happens on failure (never a dead end).")
    critical_failure_stakes: str | None = Field(default=None, description="Optional harsher consequence for a natural 1.")
    reason: str = Field(description="Brief justification of the ruling and DC.")


class Adjudication(AdjudicationRuling):
    """A ruling plus its deterministic dice resolution. The outcome is canon."""
    rolls: list[int] = Field(default_factory=list)
    total: int | None = None
    outcome: Literal["success", "failure", "critical_success", "critical_failure"] | None = None

    def render_roll_line(self, player_name: str) -> str:
        if not self.rolls:
            return ""
        kept = max(self.rolls) if self.advantage == "advantage" else min(self.rolls) if self.advantage == "disadvantage" else self.rolls[0]
        rolls = "/".join(str(r) for r in self.rolls)
        mod = f" {self.modifier:+d}" if self.modifier else ""
        adv = f", {self.advantage}" if self.advantage != "normal" else ""
        outcome = (self.outcome or "").replace("_", " ")
        label = f" — {self.check_label}" if self.check_label else ""
        return f"🎲 {player_name}{label} vs DC {self.dc}: d20[{rolls}] kept {kept}{mod} = {self.total}{adv} → {outcome}"

    def render(self) -> str:
        lines = [f"Ruling: {self.ruling} -- {self.reason}"]
        if self.ruling == "roll" and self.check_label:
            adv = f", {self.advantage}" if self.advantage != "normal" else ""
            mod = f", modifier {self.modifier:+d}" if self.modifier else ""
            lines.append(f"Check: {self.check_label} vs DC {self.dc}{adv}{mod}")
        if self.applied_effects:
            lines.append(f"Status effects applied: {', '.join(self.applied_effects)}")
        if self.rolls:
            lines.append(f"Dice: d20[{'/'.join(str(r) for r in self.rolls)}] -> total {self.total}")
        if self.outcome:
            lines.append(f"OUTCOME (canon, must be respected): {self.outcome}")
        lines.extend([f"Success stakes: {self.success_stakes}", f"Failure stakes: {self.failure_stakes}"])
        if self.critical_failure_stakes:
            lines.append(f"Critical failure stakes: {self.critical_failure_stakes}")
        return "\n".join(lines)


class ThreadUpdate(BaseModel):
    title: str = Field(description="Short stable title of the quest thread.")
    action: Literal["open", "progress", "resolve", "abandon"]
    note: str = Field(default="", description="One-line development or closing note.")


class ClockAdvance(BaseModel):
    faction: str = Field(description="Faction name exactly as it appears in the clock list.")
    ticks: int = Field(ge=0, le=3, description="Ticks to advance (1 steady, 2 major).")
    reason: str = Field(default="")
    next_move: str | None = None


class NewClock(BaseModel):
    faction_name: str
    goal: str
    ticks_max: int = Field(default=6, ge=2, le=12)
    next_move: str = ""


class MechanicsDocUpdate(BaseModel):
    title: str = Field(description="Exact title of the existing mechanics document being replaced.")
    content: str = Field(description="Complete new markdown of the document with tracked state updated.")


class CharacterMemoryItem(BaseModel):
    character_name: str = Field(description="Exact name of the character this memory belongs to.")
    title: str = Field(description="Short memory title, one line.")
    content: str = Field(description="What the character personally learned, felt, or decided, from their POV.")


class SceneEpilogue(BaseModel):
    changed: bool = Field(description="True when the conversation indicates a scene change (time skip, new location, or scene end).")
    location: str | None = Field(default=None, description="New location when moved; None when unchanged.")
    world_clock: str | None = Field(default=None, description="New narrative time when meaningful time passed; None otherwise.")
    mechanics_updates: list[MechanicsDocUpdate] = Field(default_factory=list)
    reason: str = Field(default="")
    scene_summary: str = Field(default="", description="2-4 sentences capturing what happened. Empty when changed is false.")
    canon_updates: list[str] = Field(default_factory=list)
    npc_updates: list[str] = Field(default_factory=list)
    unresolved_hooks: list[str] = Field(default_factory=list)
    player_preferences: str | None = None
    character_memories: list[CharacterMemoryItem] = Field(default_factory=list)


class StatusEffectPatch(BaseModel):
    name: str = Field(description="Condition name, e.g. 'poisoned', 'inspired', 'shaken'.")
    note: str | None = None
    affects: str | None = Field(default=None, description="Which rolls the condition modifies, or null.")
    roll_modifier: int = 0
    advantage: Literal["advantage", "normal", "disadvantage"] = "normal"


class ParticipantStateUpdate(BaseModel):
    name: str = Field(description="Exact name of the player or active NPC whose state changes.")
    stats_set: dict[str, int] = Field(default_factory=dict)
    status_added: list[StatusEffectPatch] = Field(default_factory=list)
    status_removed: list[str] = Field(default_factory=list)
    modifiers_set: dict[str, int] = Field(default_factory=dict)
    notes: str | None = None


class NPCIntroduction(BaseModel):
    name: str = Field(description="Desired name for the new character.")
    build_instructions: str = Field(description="Detailed instructions for personality, appearance, role, and backstory.")
    entrance_narration: str = Field(description="Player-ready prose describing how this NPC enters the scene.")


class CharacterCard(BaseModel):
    description: str = Field(description="The complete W++ character card and nothing else.")
    status_effects: list[StatusEffectPatch] = Field(default_factory=list)


class DMPlan(BaseModel):
    opening_narration: str | None = Field(default=None, description=(
        "OPTIONAL scene-setting or environmental narration BEFORE any NPC speaks, written as "
        "PLAYER-READY PROSE in the Narrator's voice. Leave None when NPC dialogue carries the moment."))
    npcs_to_introduce: list[NPCIntroduction] = Field(default_factory=list)
    closing_narration: str | None = Field(default=None, description=(
        "OPTIONAL DM narration AFTER NPCs have spoken, written as PLAYER-READY PROSE in the Narrator's voice."))
    new_world_events: list[str] = Field(default_factory=list)
    secret_notes: str | None = None
    adjudication: AdjudicationRuling | None = Field(default=None, description=(
        "Populate ONLY when the player's move attempts an uncertain AND consequential in-character action."))
    action_outcome: str | None = Field(default=None, description=(
        "How the player's action resolves. Leave None when adjudicated (stakes become the outcome after dice)."))
    time_location_update: str | None = None
    mechanics_moved: bool = False
    thread_updates: list[ThreadUpdate] = Field(default_factory=list)
    clock_advances: list[ClockAdvance] = Field(default_factory=list)
    world_clock_update: str | None = None
    offscreen_simulation: bool = False
    participant_state_updates: list[ParticipantStateUpdate] = Field(default_factory=list)


class ContinuityVerdict(BaseModel):
    approved: bool = Field(description="True unless a check is clearly violated (secrets, agency, coherence, state).")
    issues: list[str] = Field(default_factory=list)


class FactionSimulation(BaseModel):
    clock_advances: list[ClockAdvance] = Field(default_factory=list)
    new_clocks: list[NewClock] = Field(default_factory=list)
    world_events: list[str] = Field(default_factory=list)
    secret_notes: str | None = None


@dataclass
class DMContext:
    """Everything a DM turn needs about the session and the current turn's state."""
    conversation: Conversation
    sink: TurnSink = field(default_factory=NullTurnSink)
    campaign_id: int = field(init=False)
    player_id: int | None = field(init=False)

    query_vector: list[float] | None = None
    location: str = ""
    world_clock: str = "(unspecified)"
    story_background: str = ""
    player_sheet: str = ""
    lore: str = ""
    world_events: str = ""
    secret_knowledge: str = ""
    open_threads: str = "(no open quest threads)"
    faction_clocks: str = "(no active faction clocks)"
    player_prefs: str = "(nothing learned yet)"
    player_state: str = "(no tracked mechanical state)"
    active_npc_states: str = "(no tracked mechanical state for active NPCs)"
    ooc: bool = False
    plan: DMPlan | None = None
    adjudication: Adjudication | None = None
    outcome_narrated: bool = False

    def __post_init__(self) -> None:
        self.campaign_id = self.conversation.campaign_id
        self.player_id = self.conversation.player_id

    def combined_messages(self, messages: list[AnyMessage], limit: int | None = None) -> list[AnyMessage]:
        combo = [*self.conversation.message_buffer, *messages]
        return combo[-min(limit, len(combo)):] if limit is not None else combo

    @staticmethod
    def last_human_query(messages: list[AnyMessage], fallback: str = "general scene") -> str:
        last = next((m for m in reversed(messages) if isinstance(m, HumanMessage)), None)
        return str(last.content) if last else fallback

    def register_character(self, character: CharacterModel) -> None:
        from database.models import CampaignParticipant

        self.conversation.add_character(character)
        self.conversation._npcs_introduced = True
        CampaignParticipant.get_or_create(campaign_id=self.campaign_id, character_id=character.id)
        logger.info(f"🎭 NPC '{character.name}' introduced to scene (campaign {self.campaign_id})")


async def run_classifier(
    skill: str, model: BaseChatModel, schema: type[T], variables: dict[str, Any], *, label: str
) -> T | None:
    """🎯 Render a classifier skill and call the model with structured output (fail-secure)."""
    from agents.skilled_agent import skill_registry

    prompt = await skill_registry.render(skill).ainvoke(variables)
    llm = model.with_structured_output(schema, strict=True)
    try:
        result = await llm.ainvoke(prompt)
    except Exception:
        logger.exception(f"💥 [{label}] classifier '{skill}' failed; returning None")
        return None
    if result is None:
        logger.warning(f"⚠️ [{label}] classifier '{skill}' returned None")
    return result


async def narrate_beats(ctx: DMContext, notes: list[tuple[str, str]], messages: list[AnyMessage]) -> list[AIMessage]:
    """📜 Emit single-beat narration directly or weave composite beats via the narrator LLM."""
    if not notes:
        return []
    prefix = f"{NARRATOR_NAME}: "
    if len(notes) == 1:
        msg = AIMessage(content=f"{prefix}{notes[0][1].strip()}", name=NARRATOR_NAME, id=str(uuid4()))
        logger.info(f"📜 Narration (direct): {msg.content[:120]}...")
        return [msg]

    from utils.llm_models import dm_narrator_model
    from utils.prompts import dm_narrator_prompt_template

    prompt = await dm_narrator_prompt_template.ainvoke({
        "narration_notes": "\n".join(f"{label}: {text}" for label, text in notes),
        "location": ctx.location,
        "story_background": ctx.story_background,
        "messages": ctx.combined_messages(messages, limit=NARRATOR_CONTEXT_WINDOW),
    })
    prompt.messages.append(AIMessage(content=prefix))
    message_id = str(uuid4())
    response = await dm_narrator_model.ainvoke(
        prompt, config={"metadata": {STREAM_MESSAGE_ID_KEY: message_id}}
    )
    content = (response.content or "").strip()
    while content.startswith(prefix):
        content = content[len(prefix):].lstrip()
    msg = AIMessage(content=f"{prefix}{content}", name=NARRATOR_NAME, id=message_id)
    logger.info(f"📜 Narration (woven): {msg.content[:120]}...")
    return [msg]
