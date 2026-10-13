"""🤖 Skill-driven tool agent: SKILL.md registry, progressive-disclosure middleware, and retry."""
import asyncio
import operator
from dataclasses import dataclass
from logging import getLogger
from pathlib import Path
from typing import Annotated, Any, Awaitable, Callable

import openai
import yaml
from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware, AgentState, ModelRequest, ModelResponse
from langchain.tools import tool
from langchain_core.messages import SystemMessage, ToolMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from database.models.lore import LoreEntry, World
from tools.campaign_admin import build_campaign_admin_tools, render_campaign_overview
from tools.lore_management import (
    delete_lore_entry,
    list_lore_entries,
    read_lore_entry,
    save_lore_entries,
    update_lore_entry,
)
from tools.npc_management import create_character, list_characters, read_character
from tools.status_effects import (
    list_character_status_effects,
    remove_character_status_effect,
    set_character_status_effect,
)
from utils.llm_models import skilled_agent_model

logger = getLogger(__name__)

SKILLS_ROOT = Path(__file__).resolve().parents[1] / "skills"
WORLD_SKILLS = ["lore-management", "npc-building"]
KNOWN_CONTEXT_LOADERS = frozenset({"lore", "campaign_overview"})

TOOL_REGISTRY: dict[str, Any] = {
    "list_lore_entries": list_lore_entries,
    "read_lore_entry": read_lore_entry,
    "save_lore_entries": save_lore_entries,
    "update_lore_entry": update_lore_entry,
    "delete_lore_entry": delete_lore_entry,
    "create_character": create_character,
    "list_characters": list_characters,
    "read_character": read_character,
    "list_character_status_effects": list_character_status_effects,
    "set_character_status_effect": set_character_status_effect,
    "remove_character_status_effect": remove_character_status_effect,
    "campaign_admin_tools": build_campaign_admin_tools,
}
TOOL_FACTORIES = {"campaign_admin_tools"}

SKILLS_PREAMBLE = """You are an assistant on the Dionysus tabletop-RPG platform, equipped with skills.

Skills are curated instruction sets for specific tasks. The skills available in this session are listed below (name: description). When the user's request matches a skill that is not yet active, call the load_skill tool with that skill's name BEFORE doing the work -- the skill's full instructions then govern how you respond. Multiple skills may be active at once.

AVAILABLE SKILLS:
{metadata}"""

MODEL_TIMEOUT_S = 180.0
MODEL_MAX_ATTEMPTS = 3
MODEL_BACKOFF_S = (10.0, 20.0)
_NON_RETRYABLE_API_ERRORS = (
    openai.BadRequestError,
    openai.AuthenticationError,
    openai.PermissionDeniedError,
    openai.NotFoundError,
    openai.UnprocessableEntityError,
    openai.ConflictError,
)


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    body: str
    tool_names: tuple[str, ...]
    context_loaders: tuple[str, ...]
    path: Path

    def resolve_tools(self, campaign_id: int | None = None) -> list:
        tools: list = []
        for name in self.tool_names:
            entry = TOOL_REGISTRY[name]
            if name in TOOL_FACTORIES:
                if campaign_id is None:
                    raise ValueError(f"🛠️ Skill '{self.name}' needs a campaign_id for its tools")
                tools.extend(entry(campaign_id))
            else:
                tools.append(entry)
        return tools


class SkillRegistry:
    """📚 Discovers and serves every SKILL.md under the skills root."""

    def __init__(self, root: Path = SKILLS_ROOT) -> None:
        self.root = root
        self._skills: dict[str, Skill] = {}
        if not self.root.is_dir():
            logger.warning(f"⚠️ Skills root '{self.root}' does not exist; no skills loaded")
            return
        for path in sorted(self.root.glob("*/SKILL.md")):
            parts = path.read_text(encoding="utf-8").split("---", 2)
            if len(parts) < 3:
                raise ValueError(f"❌ {path}: missing YAML frontmatter delimited by '---'")
            fm = yaml.safe_load(parts[1]) or {}
            name, desc = fm.get("name"), fm.get("description")
            if not name or not desc:
                raise ValueError(f"❌ {path}: frontmatter requires 'name' and 'description'")
            tool_names = fm.get("tools") or []
            if unknown_tools := [t for t in tool_names if t not in TOOL_REGISTRY]:
                raise ValueError(f"❌ {path}: unknown tools in frontmatter: {unknown_tools}")
            loaders, singular = fm.get("context_loaders"), fm.get("context_loader")
            if loaders is not None and singular is not None:
                raise ValueError(f"❌ {path}: use context_loaders or context_loader, not both")
            raw_loaders = loaders if loaders is not None else ([singular] if singular is not None else [])
            if not isinstance(raw_loaders, list) or not all(isinstance(k, str) for k in raw_loaders):
                raise ValueError(f"❌ {path}: context_loaders must be a list of strings")
            if unknown_loaders := [k for k in raw_loaders if k not in KNOWN_CONTEXT_LOADERS]:
                raise ValueError(f"❌ {path}: unknown context_loaders: {unknown_loaders}")
            self._skills[name] = Skill(
                name=name,
                description=desc,
                body=parts[2].strip(),
                tool_names=tuple(tool_names),
                context_loaders=tuple(dict.fromkeys(raw_loaders)),
                path=path,
            )
        logger.info(f"📚 Skill registry: {len(self._skills)} skill(s) from '{self.root}'")

    def get(self, name: str) -> Skill:
        if name not in self._skills:
            available = ", ".join(sorted(self._skills)) or "(none)"
            raise KeyError(f"❌ Unknown skill '{name}'. Available: {available}")
        return self._skills[name]

    def render(self, name: str) -> ChatPromptTemplate:
        return ChatPromptTemplate.from_messages([
            ("system", self.get(name).body),
            MessagesPlaceholder("messages"),
        ])


skill_registry = SkillRegistry()


class SkillsState(AgentState):
    active_skills: Annotated[list[str], operator.add]
    skill_context: dict[str, str]


class SkillsMiddleware(AgentMiddleware):
    """🧩 Injects skill metadata, activates skills on demand, scopes tools per call."""

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
            registry.get(name)
        self._pre_active = list(active or [])
        if unknown := [n for n in self._pre_active if n not in skills]:
            raise ValueError(f"🧩 Pre-active skills not in the session's skill set: {unknown}")
        self._world_name = world_name
        self._campaign_id = campaign_id
        self._registered_tools: dict[str, Any] = {}
        for name in skills:
            for t in registry.get(name).resolve_tools(campaign_id):
                self._registered_tools.setdefault(t.name, t)

        available = set(skills)

        @tool
        async def load_skill(
            name: str,
            tool_call_id: Annotated[str, InjectedToolCallId],
            state: Annotated[SkillsState, InjectedState],
        ) -> Command:
            """Load the full instructions for one of your available skills."""
            if name not in available:
                known = ", ".join(sorted(available))
                logger.warning(f"⚠️ load_skill called with unavailable skill '{name}'")
                return Command(update={"messages": [ToolMessage(
                    content=f"❌ Skill '{name}' is not available in this session. Available: {known}",
                    tool_call_id=tool_call_id,
                )]})
            skill = registry.get(name)
            logger.info(f"🧩 Skill '{name}' activated")
            ctx = state["skill_context"]
            body = skill.body.format(
                world_name=world_name,
                campaign_id=campaign_id,
                **{key: ctx[key] for key in skill.context_loaders},
            )
            return Command(update={
                "active_skills": [skill.name],
                "messages": [ToolMessage(
                    content=f"📚 Skill '{skill.name}' activated. Instructions:\n\n{body}",
                    tool_call_id=tool_call_id,
                )],
            })

        self.tools = [load_skill]

    async def abefore_agent(self, state: SkillsState, runtime) -> dict[str, Any] | None:
        loader_keys = {k for n in self._skill_names for k in self._registry.get(n).context_loaders}
        contexts: dict[str, str] = {}
        if "campaign_overview" in loader_keys:
            if self._campaign_id is None:
                raise ValueError("🧩 skill_context needs campaign_overview but no campaign_id is bound")
            contexts["campaign_overview"] = await asyncio.to_thread(render_campaign_overview, self._campaign_id)
            logger.info(f"📋 Loaded overview for campaign {self._campaign_id}")
        if "lore" in loader_keys:
            if not self._world_name:
                raise ValueError("🧩 skill_context needs lore but no world_name is bound")
            world = await asyncio.to_thread(World.get_world_by_name, self._world_name)
            if world is None:
                raise ValueError(f"🧩 World '{self._world_name}' not found")
            entries = await asyncio.to_thread(LoreEntry.preview_entries, world)
            contexts["lore"] = "\n".join(f"- id={e['id']} | title='{e['title']}'" for e in entries)
            logger.info(f"🌍 Loaded {world.entry_count} lore entries for world '{self._world_name}'")
        if unknown := loader_keys - contexts.keys():
            raise ValueError(f"🧩 Unsupported context_loaders: {sorted(unknown)}")
        if self._pre_active:
            logger.info(f"🧩 Session starts with pre-activated skills: {self._pre_active}")
        return {"active_skills": self._pre_active, "skill_context": contexts}

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        active = [self._registry.get(n) for n in dict.fromkeys(request.state["active_skills"])]
        active_names = {t.name for s in active for t in s.resolve_tools(self._campaign_id)}
        tools = [*self.tools, *(t for n, t in self._registered_tools.items() if n in active_names)]
        metadata = "\n".join(
            f"- {s.name}: {s.description}" for s in (self._registry.get(n) for n in self._skill_names)
        )
        return await handler(request.override(
            system_message=SystemMessage(content=SKILLS_PREAMBLE.format(metadata=metadata)),
            tools=tools,
        ))


class RetryMiddleware(AgentMiddleware):
    """🔁 Retries transient model-call failures with backoff."""

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
                    logger.error(f"🤖 [{self._label}] model call failed after {attempt} attempts: {e}")
                    raise
                backoff = MODEL_BACKOFF_S[min(attempt - 1, len(MODEL_BACKOFF_S) - 1)]
                logger.warning(f"🤖 [{self._label}] attempt {attempt} failed ({e}); retrying in {backoff:.0f}s")
                await asyncio.sleep(backoff)
        raise last_exc or RuntimeError(f"[{self._label}] model invoke failed without exception")


def spawn_skilled_agent(
    skills: list[str],
    *,
    active: list[str] | None = None,
    world_name: str | None = None,
    campaign_id: int | None = None,
    name: str = "skilled_agent",
):
    mw = SkillsMiddleware(skills, active=active, world_name=world_name, campaign_id=campaign_id)
    return create_agent(
        model=skilled_agent_model,
        tools=list(mw._registered_tools.values()),
        middleware=[mw, RetryMiddleware(name=name)],
        name=name,
    )
