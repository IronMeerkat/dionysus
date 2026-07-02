"""Structured schemas for the DM supervisor: plans, rulings, verdicts, state."""
import operator
from typing import Annotated, Literal

from langchain_core.messages import AnyMessage
from pydantic import BaseModel, Field

NARRATOR_NAME = "Narrator"


# ------------------------------------------------------------------
# Intent routing
# ------------------------------------------------------------------

class IntentReading(BaseModel):
    """The intent router's classification of the player's latest message."""
    intent_type: Literal["dialogue", "action", "ooc_question", "rules_question", "meta"] = Field(
        description=(
            "dialogue: in-character speech/social play with no uncertain outcome. "
            "action: the player attempts something in the world. "
            "ooc_question: out-of-character question to the DM. "
            "rules_question: question about game mechanics. "
            "meta: request about the session itself (tone, pacing, recap)."))
    scene_mode: Literal["social", "exploration", "investigation", "confrontation", "travel", "downtime"] = Field(
        description="The dominant frame for this turn, used as a pacing hint.")
    needs_adjudication: bool = Field(description=(
        "True only for in-character actions whose outcome is genuinely uncertain "
        "AND consequential. False for dialogue, trivial actions, and questions."))
    summary: str = Field(description="One short line stating what the player is trying to accomplish.")

    def render(self) -> str:
        return (
            f"Intent: {self.intent_type} | Scene mode: {self.scene_mode} | "
            f"Needs adjudication: {self.needs_adjudication}\n"
            f"The player wants: {self.summary}"
        )


# ------------------------------------------------------------------
# Rules adjudication
# ------------------------------------------------------------------

class AdjudicationRuling(BaseModel):
    """The rules referee's ruling on an uncertain player action (pre-dice)."""
    ruling: Literal["auto_success", "auto_failure", "roll", "impossible"] = Field(
        description=(
            "auto_success: nothing meaningfully opposes the action. "
            "auto_failure: cannot succeed as attempted, but something happens. "
            "roll: success and failure are both plausible and interesting. "
            "impossible: cannot be done without means the player lacks."))
    check_label: str | None = Field(default=None, description=(
        "Name of the check in plain D&D style, e.g. 'Dexterity (Stealth)'. Only for ruling='roll'."))
    dc: int | None = Field(default=None, ge=5, le=30, description=(
        "Difficulty class: 5 very easy, 10 easy, 15 moderate, 20 hard, 25 very hard, "
        "30 nearly impossible. Only for ruling='roll'."))
    advantage: Literal["advantage", "normal", "disadvantage"] = Field(
        default="normal", description="Whether circumstances favor or hinder the attempt.")
    success_stakes: str = Field(description="What concretely happens on success.")
    failure_stakes: str = Field(description=(
        "What concretely happens on failure -- never a dead end: it costs time, "
        "raises alarms, burns goodwill, or reveals the player."))
    critical_failure_stakes: str | None = Field(default=None, description=(
        "Optional harsher consequence reserved for a natural 1."))
    reason: str = Field(description="Brief justification of the ruling and DC.")


class Adjudication(AdjudicationRuling):
    """A ruling plus its deterministic dice resolution. The outcome is canon."""
    rolls: list[int] = Field(default_factory=list, description="Raw d20 rolls (deterministic, code-rolled).")
    total: int | None = Field(default=None, description="Kept die plus modifiers.")
    outcome: Literal["success", "failure", "critical_success", "critical_failure"] | None = Field(
        default=None, description="The resolved outcome this turn must respect.")

    def render(self) -> str:
        lines = [f"Ruling: {self.ruling} -- {self.reason}"]
        if self.ruling == "roll" and self.check_label:
            adv = f", {self.advantage}" if self.advantage != "normal" else ""
            lines.append(f"Check: {self.check_label} vs DC {self.dc}{adv}")
        if self.rolls:
            rolls = "/".join(str(r) for r in self.rolls)
            lines.append(f"Dice: d20[{rolls}] -> total {self.total}")
        if self.outcome:
            lines.append(f"OUTCOME (canon, must be respected): {self.outcome}")
        lines.append(f"Success stakes: {self.success_stakes}")
        lines.append(f"Failure stakes: {self.failure_stakes}")
        if self.critical_failure_stakes:
            lines.append(f"Critical failure stakes: {self.critical_failure_stakes}")
        return "\n".join(lines)


# ------------------------------------------------------------------
# World-state updates (applied deterministically by the canon manager)
# ------------------------------------------------------------------

class ThreadUpdate(BaseModel):
    """A structured change to a quest thread (open narrative loop)."""
    title: str = Field(description="Short stable title of the thread, e.g. 'The missing children'.")
    action: Literal["open", "progress", "resolve", "abandon"] = Field(
        description="open: start tracking. progress: append a development. resolve/abandon: close the loop.")
    note: str = Field(default="", description="One-line development or closing note.")


class ClockAdvance(BaseModel):
    """A tick on a faction's progress clock."""
    faction: str = Field(description="Faction name exactly as it appears in the clock list.")
    ticks: int = Field(ge=0, le=3, description="How many ticks to advance (1 steady, 2 major).")
    reason: str = Field(default="", description="Why the agenda advanced.")
    next_move: str | None = Field(default=None, description="Optional update to the faction's next move.")


class NewClock(BaseModel):
    """A brand-new faction agenda worth tracking."""
    faction_name: str = Field(description="Name of the faction.")
    goal: str = Field(description="What the faction is working toward.")
    ticks_max: int = Field(default=6, ge=2, le=12, description="Clock size; 4 fast, 6 standard, 8+ slow.")
    next_move: str = Field(default="", description="The faction's immediate next step.")


# ------------------------------------------------------------------
# NPC orchestration
# ------------------------------------------------------------------

class NPCDirective(BaseModel):
    """Instructions from the DM to a single NPC for this turn."""
    name: str = Field(description="Character name exactly as it appears in the active NPC list.")
    guidance: str = Field(description="What the DM wants this NPC to focus on, say, or do this turn.")
    withheld_info: list[str] = Field(default_factory=list, description=(
        "Facts this NPC must NOT reveal or reference (information asymmetry)."))


class ParticipantStateUpdate(BaseModel):
    """A structured patch to a participant's live mechanical state this turn.

    Only patch what changed; never rewrite a whole sheet. Stats and modifiers
    are set/overwritten by key; status effects are added or removed. Applied
    deterministically by the canon manager -- the LLM never writes state directly.
    """
    name: str = Field(description=(
        "Exact name of the participant whose state changes this turn. "
        "For role='player' this is the player character's name; for role='npc' "
        "it must match an NPC in the active NPC list."))
    role: Literal["player", "npc"] = Field(description=(
        "player = the player character; npc = a non-player character in the scene."))
    stats_set: dict[str, int] = Field(default_factory=dict, description=(
        "Stats to set or overwrite by key, e.g. {'hp': 8, 'ac': 14}. "
        "Empty dict leaves stats unchanged."))
    status_added: list[str] = Field(default_factory=list, description=(
        "Status effects to add, e.g. ['poisoned', 'frightened']. Empty to add none."))
    status_removed: list[str] = Field(default_factory=list, description=(
        "Status effects to remove, e.g. ['inspired']. Empty to remove none."))
    modifiers_set: dict[str, int] = Field(default_factory=dict, description=(
        "Modifiers to set or overwrite by key, e.g. {'attack': 2, 'stealth': -1}. "
        "Set a modifier to 0 to effectively clear it. Empty leaves modifiers unchanged."))
    notes: str | None = Field(default=None, description=(
        "Optional replacement for the freeform state notes. Null leaves notes unchanged."))


class NPCIntroduction(BaseModel):
    """Request from the DM to spawn a brand-new NPC mid-session."""
    name: str = Field(description="Desired name for the new character.")
    build_instructions: str = Field(description=(
        "Detailed instructions passed to the NPC builder describing "
        "personality, appearance, role, and backstory."))
    entrance_narration: str = Field(description=(
        "Brief note on how this NPC enters the scene (expanded by the DM narrator)."))


class BuildReview(BaseModel):
    """The DM's verdict on a character card drafted by the NPC builder."""
    approved: bool = Field(description=(
        "True only if a complete, on-brief W++ card with the exact requested name was presented."))
    feedback: str = Field(description=(
        "Answers to the builder's questions, or specific critique of the card. "
        "Confirmation text if approved."))


# ------------------------------------------------------------------
# The DM plan
# ------------------------------------------------------------------

class DMPlan(BaseModel):
    """The Dungeon Master's structured plan for this turn."""
    opening_narration: str | None = Field(default=None, description=(
        "OPTIONAL scene-setting or environmental narration BEFORE any NPC speaks. Most turns need "
        "none -- leave None whenever NPC dialogue alone carries the moment."))
    responding_npcs: list[NPCDirective] = Field(default_factory=list, description=(
        "Ordered list of NPCs that should respond this turn, with per-NPC guidance. "
        "Empty if no NPC should speak."))
    npcs_to_introduce: list[NPCIntroduction] = Field(default_factory=list, description=(
        "New NPCs to create and add to the scene. Empty if no new NPCs are needed."))
    closing_narration: str | None = Field(default=None, description=(
        "OPTIONAL DM narration AFTER NPCs have spoken (consequences, cliffhangers). Most turns need "
        "none -- leave None unless the moment genuinely demands a narrative beat."))
    new_world_events: list[str] = Field(default_factory=list, description=(
        "Significant facts or consequences to persist in the world event log. "
        "Empty if nothing noteworthy happened."))
    secret_notes: str | None = Field(default=None, description=(
        "DM-only knowledge that should be remembered for future turns "
        "but NEVER revealed to NPCs or the player."))
    action_outcome: str | None = Field(default=None, description=(
        "How the player's attempted action resolves. When the referee adjudicated the action, "
        "this MUST narratively express the adjudicated outcome -- a failed roll stays a failure. "
        "None for plain dialogue. Narrate failures as interesting story beats, not dead ends."))
    time_location_update: str | None = Field(default=None, description=(
        "New location or time-of-day description if the scene changes. "
        "None if the scene stays the same."))
    thread_updates: list[ThreadUpdate] = Field(default_factory=list, description=(
        "Quest threads to open, progress, resolve, or abandon this turn. "
        "Open threads for promises, mysteries, and debts; close them when settled."))
    clock_advances: list[ClockAdvance] = Field(default_factory=list, description=(
        "Faction clocks to tick because the player's actions helped or provoked them. "
        "Empty most turns."))
    world_clock_update: str | None = Field(default=None, description=(
        "New narrative time when meaningful time passes, e.g. 'Day 3, dusk'. "
        "None if barely any time passed."))
    offscreen_simulation: bool = Field(default=False, description=(
        "True when this turn was loud, consequential, or scene-ending, so the "
        "world should advance offscreen (faction simulation). False for ordinary exchanges."))
    participant_state_updates: list[ParticipantStateUpdate] = Field(default_factory=list, description=(
        "Mechanical state changes to apply to a player or NPC this turn "
        "(injury, healing, a new condition like poisoned/frightened, a buff or "
        "debuff, death, unconsciousness). Patch only what changed. Empty when no "
        "mechanical state changed -- most turns need none."))


# ------------------------------------------------------------------
# Continuity review
# ------------------------------------------------------------------

class ContinuityVerdict(BaseModel):
    """The continuity checker's verdict on a DM plan."""
    approved: bool = Field(description=(
        "True unless a check is clearly violated (cast, secrets, agency, adjudication, coherence)."))
    issues: list[str] = Field(default_factory=list, description=(
        "Concrete, actionable problems the planner must fix. Empty when approved."))


# ------------------------------------------------------------------
# Scene memory + faction simulation
# ------------------------------------------------------------------

class SceneSummary(BaseModel):
    """Distilled memory of a concluded scene."""
    scene_summary: str = Field(description="2-4 sentences capturing what happened and why it mattered.")
    canon_updates: list[str] = Field(default_factory=list, description=(
        "Discrete facts that became true, one per entry, past tense."))
    npc_updates: list[str] = Field(default_factory=list, description=(
        "How named NPCs' attitudes, plans, or circumstances changed."))
    unresolved_hooks: list[str] = Field(default_factory=list, description=(
        "Questions raised but unanswered, promises unkept, threats looming."))
    player_preferences: str | None = Field(default=None, description=(
        "Clear evidence of what the player enjoys or avoids. Null when unsure."))


class FactionSimulation(BaseModel):
    """Offscreen faction moves produced by the faction simulator."""
    clock_advances: list[ClockAdvance] = Field(default_factory=list, description=(
        "Existing clocks that tick forward, with reasons."))
    new_clocks: list[NewClock] = Field(default_factory=list, description=(
        "New faction agendas worth tracking. Use sparingly."))
    world_events: list[str] = Field(default_factory=list, description=(
        "Facts that became true offscreen, phrased to surface later as rumors or "
        "changed circumstances. Prefix rumor-flavored ones with 'Rumor:'."))
    secret_notes: str | None = Field(default=None, description=(
        "DM-only notes on faction intentions and hidden causes."))


# ------------------------------------------------------------------
# Graph state
# ------------------------------------------------------------------

class DungeonMasterState(BaseModel):
    messages: Annotated[list[AnyMessage], operator.add]
    plan: DMPlan | None = None
    lore: str = ""
    world_events: str = ""
    secret_knowledge: str = ""
    # Supervisor pipeline
    intent: IntentReading | None = None
    adjudication: Adjudication | None = None
    continuity_notes: str = ""
    plan_attempts: int = 0
    # Structured world state (rendered prompt-ready by the context loader)
    open_threads: str = "(no open quest threads)"
    faction_clocks: str = "(no active faction clocks)"
    player_prefs: str = ""
    # Live participant mechanical state (rendered prompt-ready by the context loader)
    player_state: str = "(no tracked mechanical state)"
    active_npc_states: str = "(no tracked mechanical state for active NPCs)"
    # NPC build negotiation loop (DM <-> npc_builder argument)
    build_queue: list[NPCIntroduction] = Field(default_factory=list)
    build_transcript: list[AnyMessage] = Field(default_factory=list)
    build_rounds: int = 0
    build_created: bool = False
