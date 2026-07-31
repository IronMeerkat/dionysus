"""🧩 Custom LangChain agent middleware: skills (progressive disclosure) + retry.

``SkillsMiddleware`` implements the Agent Skills pattern without deepagents:

1. Discovery (layer 1): the system prompt lists only each available skill's
   name + description.
2. Activation (layer 2): the agent calls the middleware-provided
   ``load_skill`` tool; the full SKILL.md body enters context as a tool
   message and the skill is marked active in state.
3. Tool scoping: each model call binds only ``load_skill`` plus the tools
   declared by the *active* skills, via ``request.override(tools=...)``.

``RetryMiddleware`` ports the model-call resilience previously hardcoded in
``agents.tool_agent`` (nano-gpt intermittently times out or stalls).
"""
import asyncio
import operator
from logging import getLogger
from typing import Annotated, Any, Awaitable, Callable

import openai
from langchain.agents.middleware import AgentMiddleware, AgentState, ModelRequest, ModelResponse
from langchain.tools import tool
from langchain_core.tools import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langchain_core.messages import SystemMessage, ToolMessage
from langgraph.types import Command

from tools.campaign_admin import render_campaign_overview
from agents.skills.registry import (
    SkillRegistry,
    resolve_skill_set_tools,
    resolve_tools,
    skill_registry,
)
from database.models.lore import LoreEntry, World

logger = getLogger(__name__)


class SkillsState(AgentState):
    """Agent state extended with skill activation and rendered context blocks."""

    active_skills: Annotated[list[str], operator.add]
    skill_context: dict[str, str]


SKILLS_PREAMBLE = """You are an assistant on the Dionysus tabletop-RPG platform, equipped with skills.

Skills are curated instruction sets for specific tasks. The skills available in this session are listed below (name: description). When the user's request matches a skill that is not yet active, call the load_skill tool with that skill's name BEFORE doing the work -- the skill's full instructions then govern how you respond. Multiple skills may be active at once.

AVAILABLE SKILLS:
{metadata}"""


class SkillsMiddleware(AgentMiddleware):
    """Injects skill metadata, activates skills on demand, scopes tools per call."""

    state_schema = SkillsState

    def __init__(
        self,
        skills: list[str],
        *,
        active: list[str] | None = None,
        world_name: str | None = None,
        campaign_id: int | None = None,
        registry: SkillRegistry = skill_registry,
    ) -> None:
        self._registry = registry
        self._skill_names = skills
        for name in skills:
            registry.get(name)  # fail fast on unknown skills at spawn time
        self._pre_active = list(active or [])
        unknown = [n for n in self._pre_active if n not in skills]
        if unknown:
            raise ValueError(f"🧩 Pre-active skills not in the session's skill set: {unknown}")
        self._world_name = world_name
        self._campaign_id = campaign_id
        self.tools = [self._make_load_skill_tool()]
        # Every skill tool the agent may execute; awrap_model_call binds only
        # the active skills' subsets per call.
        self._registered_tools = {
            tool.name: tool
            for tool in resolve_skill_set_tools(
                [registry.get(name) for name in skills],
                campaign_id=campaign_id,
            )
        }

    def registered_tools(self) -> list:
        """Tools that must be registered at create_agent time."""
        return list(self._registered_tools.values())

    def _make_load_skill_tool(self):
        registry = self._registry
        available = set(self._skill_names)

        @tool
        async def load_skill(
            name: str,
            tool_call_id: Annotated[str, InjectedToolCallId],
            state: Annotated[SkillsState, InjectedState],
        ) -> Command:
            """Load the full instructions for one of your available skills.

            Call this BEFORE starting work that matches a skill's description.
            The skill's instructions are returned and its tools become available.
            """
            if name not in available:
                known = ", ".join(sorted(available))
                logger.warning(f"⚠️ load_skill called with unavailable skill '{name}'")
                return Command(update={
                    "messages": [ToolMessage(
                        content=f"❌ Skill '{name}' is not available in this session. Available: {known}",
                        tool_call_id=tool_call_id,
                    )],
                })
            skill = registry.get(name)
            logger.info(f"🧩 Skill '{name}' activated")
            ctx = state["skill_context"]
            # Fail-secure: only the skill's declared loaders; missing keys raise.
            body = skill.body.format(
                world_name=self._world_name,
                campaign_id=self._campaign_id,
                **{key: ctx[key] for key in skill.context_loaders},
            )
            return Command(update={
                "active_skills": [skill.name],
                "messages": [ToolMessage(
                    content=f"📚 Skill '{skill.name}' activated. Instructions:\n\n{body}",
                    tool_call_id=tool_call_id,
                )],
            })

        return load_skill

    async def abefore_agent(self, state: SkillsState, runtime) -> dict[str, Any] | None:
        """Seed pre-activated skills and load declared skill_context blocks.

        Fail-secure: missing session bindings or unknown loader keys raise;
        empty lore catalogs are allowed (valid empty data).
        """
        loader_keys = {
            key
            for name in self._skill_names
            for key in self._registry.get(name).context_loaders
        }
        contexts: dict[str, str] = {}

        if "campaign_overview" in loader_keys:
            if self._campaign_id is None:
                raise ValueError(
                    "🧩 skill_context needs campaign_overview but no campaign_id is bound"
                )
            overview = await asyncio.to_thread(render_campaign_overview, self._campaign_id)
            logger.info(f"📋 Loaded overview for campaign {self._campaign_id}")
            contexts["campaign_overview"] = overview

        if "lore" in loader_keys:
            if not self._world_name:
                raise ValueError("🧩 skill_context needs lore but no world_name is bound")
            world = await asyncio.to_thread(World.get_world_by_name, self._world_name)
            if world is None:
                raise ValueError(f"🧩 World '{self._world_name}' not found")
            entries = await asyncio.to_thread(LoreEntry.preview_entries, world)
            contexts["lore"] = "\n".join(f"- id={e['id']} | title='{e['title']}'" for e in entries)
            logger.info(f"🌍 Loaded {world.entry_count} lore entries for world '{self._world_name}'")

        unknown = loader_keys - contexts.keys()
        if unknown:
            raise ValueError(f"🧩 Unsupported context_loaders: {sorted(unknown)}")

        if self._pre_active:
            logger.info(f"🧩 Session starts with pre-activated skills: {self._pre_active}")
        return {"active_skills": self._pre_active, "skill_context": contexts}


    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        state = request.state
        active = [
            self._registry.get(name)
            for name in dict.fromkeys(state["active_skills"])
        ]

        active_tool_names = {
            tool.name
            for skill in active
            for tool in resolve_tools(skill, campaign_id=self._campaign_id)
        }
        tools = [
            *self.tools,
            *(tool for name, tool in self._registered_tools.items() if name in active_tool_names),
        ]

        return await handler(request.override(
            system_message=SystemMessage(content=SKILLS_PREAMBLE.format(metadata=self._registry.metadata_listing(self._skill_names))),
            tools=tools,
        ))


# ---------------------------------------------------------------------------
# Retry middleware
# ---------------------------------------------------------------------------

# Model call resilience: the nano-gpt endpoint intermittently returns a
# server-side "Request timed out" SSE error (raised as openai.APIError) or
# silently stalls. Give each attempt a generous 3-minute cap and retry with
# backoff so a single flaky call doesn't kill the whole turn.
MODEL_TIMEOUT_S = 180.0
MODEL_MAX_ATTEMPTS = 3
MODEL_BACKOFF_S = (10.0, 20.0)

# Permanent client errors -- retrying won't change the outcome, so fail fast.
_NON_RETRYABLE_API_ERRORS = (
    openai.BadRequestError,
    openai.AuthenticationError,
    openai.PermissionDeniedError,
    openai.NotFoundError,
    openai.UnprocessableEntityError,
    openai.ConflictError,
)


class RetryMiddleware(AgentMiddleware):
    """Retries transient model-call failures with backoff, around every LLM call."""

    def __init__(self, *, name: str = "skilled_agent") -> None:
        self._label = name

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        last_exc: Exception | None = None
        for attempt in range(1, MODEL_MAX_ATTEMPTS + 1):
            try:
                return await asyncio.wait_for(handler(request), timeout=MODEL_TIMEOUT_S)
            except _NON_RETRYABLE_API_ERRORS as e:
                logger.error(f"🤖 [{self._label}] model call hit non-retryable {type(e).__name__}: {e}")
                raise
            except (openai.APIError, asyncio.TimeoutError) as e:
                last_exc = e
                if attempt >= MODEL_MAX_ATTEMPTS:
                    logger.error(
                        f"🤖 [{self._label}] model call failed after {attempt}/{MODEL_MAX_ATTEMPTS} "
                        f"attempts: {type(e).__name__}: {e}"
                    )
                    raise
                backoff = MODEL_BACKOFF_S[min(attempt - 1, len(MODEL_BACKOFF_S) - 1)]
                logger.warning(
                    f"🤖 [{self._label}] model call attempt {attempt}/{MODEL_MAX_ATTEMPTS} "
                    f"failed ({type(e).__name__}: {e}); retrying in {backoff:.0f}s"
                )
                await asyncio.sleep(backoff)
        raise last_exc or RuntimeError(f"[{self._label}] model invoke failed without exception")
