"""The DM brain: produce a structured plan for the turn, adjudication included."""
import asyncio
from logging import getLogger
from uuid import uuid4

from langchain_core.messages import AIMessage, SystemMessage

from agents.dungeon_master.builder import register_character_in_scene
from agents.dungeon_master.context import DMContext
from agents.dungeon_master.schemas import Adjudication, DMPlan, DungeonMasterState, NPCIntroduction
from agents.skills.registry import skill_registry
from contracts.turn_events import DICE_SPEAKER
from database.models import Character as CharacterModel
from database.session_utils import embedder
from hephaestus.settings import settings
from tools.dice import resolve_check
from tools.mechanics import list_mechanics, render_mechanics_full
from tools.status_effects import render_active_status_effects_by_id
from utils.llm_models import dm_planner_model
from utils.prompts import dm_planner_prompt_template

logger = getLogger(__name__)

DEFAULT_DC = 11


def _resolve_adjudication(plan: DMPlan) -> Adjudication | None:
    """🎲 Turn the plan's ruling into a canon outcome with deterministic dice.

    The planner only sets up the situation (ruling, DC, stakes); the dice
    module rolls. The ruling's stakes become the plan's action_outcome, so
    downstream nodes (narrator, continuity checker, epilogue) see exactly the
    same state shape the old rules_referee -> planner chain produced.
    """
    ruling = plan.adjudication
    if ruling is None:
        return None

    adjudication = Adjudication(**ruling.model_dump())
    if ruling.ruling == "roll":
        check = resolve_check(
            dc=ruling.dc or DEFAULT_DC,
            advantage=ruling.advantage,
            modifier=ruling.modifier,
        )
        adjudication.rolls = check.rolls
        adjudication.total = check.total
        adjudication.outcome = check.outcome
    elif ruling.ruling == "auto_success":
        adjudication.outcome = "success"
    else:  # auto_failure | impossible
        adjudication.outcome = "failure"

    if adjudication.outcome == "critical_failure" and ruling.critical_failure_stakes:
        plan.action_outcome = ruling.critical_failure_stakes
    elif adjudication.outcome in ("success", "critical_success"):
        plan.action_outcome = ruling.success_stakes
    else:
        plan.action_outcome = ruling.failure_stakes

    logger.info(f"⚖️ Adjudication:\n{adjudication.render()}")
    return adjudication


async def _match_existing_character(
    ctx: DMContext, intro: NPCIntroduction, tau: float
) -> tuple[CharacterModel, float] | None:
    """🔎 The closest existing character to a planned introduction, or None.

    Fail-secure: any embedding/search failure logs and returns None so the
    intro proceeds through the normal build loop -- an introduction is never
    silently skipped because the embedder or the search hiccuped.
    """
    try:
        vector = await embedder.aembed_query(
            CharacterModel.embedding_text(intro.name, intro.build_instructions)
        )
        exclude = (ctx.player_id,) if ctx.player_id is not None else ()
        neighbors = await asyncio.to_thread(CharacterModel.nearest_by_vector, vector, 1, exclude)
    except Exception:
        logger.exception(f"💥 Dedup search failed for intro '{intro.name}'; proceeding with the normal build")
        return None
    if not neighbors:
        return None
    character, distance = neighbors[0]
    if distance > tau:
        logger.info(
            f"🔎 Intro '{intro.name}' nearest existing character is '{character.name}' "
            f"at L2={distance:.3f} > tau={tau}; building fresh"
        )
        return None
    return character, distance


async def _dedup_npc_intros(ctx: DMContext, plan: DMPlan) -> list[NPCIntroduction]:
    """♻️ Semantic dedup of planned NPC introductions against existing characters.

    A match under ``tau_dedup`` means the planner reinvented someone who
    already exists under a variant name/description: the intro leaves the
    build queue, its name (and any directive using it) is rewritten to the
    matched character's exact name so registration and the responding-NPC
    directives line up, and the character joins the scene through the same
    path the registrar uses.
    """
    tau = settings.memory.dedup.tau_dedup
    queue: list[NPCIntroduction] = []
    for intro in plan.npcs_to_introduce:
        match = await _match_existing_character(ctx, intro, tau)
        if match is None:
            queue.append(intro)
            continue
        character, distance = match
        old_name = intro.name
        if character.name != old_name:
            intro.name = character.name
            for directive in plan.responding_npcs:
                if directive.name == old_name:
                    directive.name = character.name
        logger.info(
            f"♻️ Intro '{old_name}' matched existing character '{character.name}' "
            f"(L2={distance:.3f} <= tau={tau}); skipping the build loop"
        )
        register_character_in_scene(ctx, character)
    return queue


def make_dm_planner(ctx: DMContext):
    plan_llm = dm_planner_model.with_structured_output(DMPlan, strict=True)

    async def dm_planner(state: DungeonMasterState) -> dict:
        """🧠 Decide what happens this turn, adjudicating actions as needed.

        There is no upstream intent reading: the planner reads the player's
        message itself and decides whether it needs adjudication, so the
        adjudication skill's instructions are always appended.
        """
        intent_block = f"The player's latest move: {DMContext.last_human_query(state)}"
        adjudication_block = (
            "(pending -- when the player's move is an in-character action with a genuinely "
            "uncertain AND consequential outcome, rule on it via the plan's adjudication field; "
            "code rolls the dice and resolves the outcome after your ruling)"
        )
        continuity_block = state.continuity_notes or "(none -- first attempt)"
        if state.continuity_notes:
            logger.info(f"🔁 Re-planning (attempt {state.plan_attempts + 1}) with continuity notes")

        prompt = await dm_planner_prompt_template.ainvoke({
            "messages": ctx.combined_messages(state),
            "lore": state.lore,
            "world_events": state.world_events,
            "secret_knowledge": state.secret_knowledge,
            "open_threads": state.open_threads,
            "faction_clocks": state.faction_clocks,
            "player_prefs": state.player_prefs,
            "contract": ctx.campaign.render_contract(),
            "active_npcs": ctx.npc_descriptions,
            "player": ctx.player_sheet,
            "player_state": state.player_state,
            "active_npc_states": state.active_npc_states,
            "location": ctx.location,
            "world_clock": ctx.world_clock,
            "story_background": ctx.story_background,
            "intent": intent_block,
            "adjudication": adjudication_block,
            "continuity_notes": continuity_block,
        })

        # Negotiated campaign mechanics are binding procedures for the plan;
        # appended (not templated) so the Langfuse prompt stays stable and
        # campaigns without mechanics pay no prompt cost. The mechanics query
        # runs on a worker thread but takes the snapshot campaign_id, so no
        # expired ORM attribute is lazily reloaded off the event loop.
        mechanics_block = await asyncio.to_thread(
            lambda: render_mechanics_full(list_mechanics(ctx.campaign_id))
        )
        if mechanics_block:
            logger.info(
                f"⚙️ Injecting campaign mechanics ({len(mechanics_block)} chars) into the planner prompt"
            )
            prompt.messages.append(SystemMessage(content=(
                "[CAMPAIGN MECHANICS]\n"
                "The following custom mechanics were negotiated for this campaign. "
                "They are binding procedures, not suggestions -- plan NPC behavior, "
                "rulings, and outcomes around them. When this turn's events move "
                "tracked state in one of these documents (a spike, a clamped rung, "
                "a recovery move, a boundary their rules key off), set the plan's "
                "mechanics_moved flag -- the scene-change updater revises the "
                "documents after the turn.\n\n"
                f"{mechanics_block}"
            )))

        # The dm-adjudication skill's instructions apply to every turn -- the
        # planner itself decides whether the player's move needs a ruling.
        # The PC's permanent sheet effects are filtered deterministically by
        # scene presence (negated effects are hidden) and appended to the
        # skill body. present_names and the player id/name are captured on
        # the event loop; the effect query/render runs on the worker thread
        # via the by-id helper so no expired ORM relationship is touched
        # off-loop.
        present_names = [c.name for c in ctx.conversation.characters]
        player_id = ctx.player_id
        player_name = ctx.player.name
        effects_block = await asyncio.to_thread(
            render_active_status_effects_by_id, player_id, player_name, present_names
        )
        skill_body = skill_registry.get("dm-adjudication").body
        if effects_block:
            skill_body += f"\n\n[ACTIVE PERMANENT STATUS EFFECTS]\n{effects_block}"
        else:
            logger.info("🧬 No active permanent status effects for the PC this turn")
        prompt.messages.append(SystemMessage(content=skill_body))

        plan: DMPlan = await plan_llm.ainvoke(prompt)
        adjudication = _resolve_adjudication(plan) if plan.adjudication else None
        if plan.closing_narration and plan.responding_npcs:
            # One less narrator call: the last responding NPC carries the beat.
            plan.responding_npcs[-1].guidance += (
                f"\nEnd your turn by conveying: {plan.closing_narration}"
            )
            logger.info("📜 Closing narration folded into the last responding NPC's guidance")
            plan.closing_narration = None
        build_queue = await _dedup_npc_intros(ctx, plan) if plan.npcs_to_introduce else []
        logger.info(
            f"📝 Plan: {len(plan.responding_npcs)} NPC(s), "
            f"{len(plan.npcs_to_introduce)} intro(s) ({len(build_queue)} to build), "
            f"{len(plan.thread_updates)} thread update(s), "
            f"{len(plan.clock_advances)} clock tick(s), "
            f"offscreen={plan.offscreen_simulation}"
        )
        return {
            "messages": [],
            "plan": plan,
            "adjudication": adjudication,
            "build_queue": build_queue,
            "plan_attempts": state.plan_attempts + 1,
        }

    return dm_planner


def make_roll_announcer(ctx: DMContext):
    async def roll_announcer(state: DungeonMasterState) -> dict:
        """🎲 Announce the resolved check as a compact chat line.

        Runs only after the plan is final (continuity approved), so dice
        re-rolled during a repair pass stay silent. Emits nothing when the
        turn had no roll. The message lands before narration and NPC
        responses, so the player sees the roll and then its consequences.
        The line streams straight to the socket with the same id the message
        is persisted under, matching the NPC executor's bubble flow.
        """
        adjudication = state.adjudication
        if not adjudication or not adjudication.rolls:
            return {"messages": []}
        line = adjudication.render_roll_line(ctx.player.name)
        message_id = str(uuid4())
        await ctx.sink.stream_start(message_id, DICE_SPEAKER)
        await ctx.sink.stream_token(message_id, line)
        await ctx.sink.stream_end(message_id, line)
        logger.info(f"🎲 Announcing roll: {line}")
        return {"messages": [AIMessage(content=line, name=DICE_SPEAKER, id=message_id)]}

    return roll_announcer
