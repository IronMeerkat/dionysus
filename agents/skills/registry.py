"""📚 Skill discovery: SKILL.md parsing plus tool and context-loader registries.

A skill is a directory under ``skills/`` containing a ``SKILL.md`` file:

    ---
    name: npc-building
    description: Design and persist NPC character cards for a campaign world
    tools: [list_lore_entries, read_lore_entry, create_character]
    context_loader: lore
    ---
    <markdown instructions, may use {var} placeholders>

Frontmatter fields:
- ``name`` / ``description`` (required): injected as layer-1 metadata so an
  agent can decide when to activate the skill.
- ``tools`` (optional): keys into ``TOOL_REGISTRY``. Values are either tool
  objects or a factory taking the session's ``campaign_id``.
- ``context_loader`` (optional): key into ``CONTEXT_LOADERS``; the loader's
  output is injected into the skill body's ``{..._context}`` placeholder.

The module is deliberately free of LangChain agent imports so it can serve
both the create_agent middleware (tool agents) and the hand-built DM graph
nodes (classifier prompts via ``SkillRegistry.render``).
"""
import asyncio
from dataclasses import dataclass
from logging import getLogger
from pathlib import Path
from typing import Any

import yaml
from langchain_core.messages import AnyMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from database import knowledge
from tools.campaign_admin import build_campaign_admin_tools, render_campaign_overview
from tools.campaign_negotiation import build_campaign_negotiation_tools
from tools.lore_management import (
    delete_lore_entry,
    list_lore_entries,
    read_lore_entry,
    save_lore_entries,
    update_lore_entry,
)
from tools.npc_management import (
    create_character,
    list_characters,
    read_character,
)
from tools.status_effects import (
    list_character_status_effects,
    remove_character_status_effect,
    set_character_status_effect,
)

logger = getLogger(__name__)

SKILLS_ROOT = Path(__file__).resolve().parents[2] / "skills"

FRONTMATTER_DELIMITER = "---"


@dataclass(frozen=True)
class Skill:
    """One parsed SKILL.md: layer-1 metadata + layer-2 instruction body."""

    name: str
    description: str
    body: str
    tool_names: tuple[str, ...]
    context_loader: str | None
    path: Path


def parse_skill_md(path: Path) -> Skill:
    """Parse one SKILL.md file into a Skill, validating required fields."""
    text = path.read_text(encoding="utf-8")
    parts = text.split(FRONTMATTER_DELIMITER, 2)
    if len(parts) < 3:
        raise ValueError(f"❌ {path}: missing YAML frontmatter delimited by '---'")

    frontmatter = yaml.safe_load(parts[1]) or {}
    body = parts[2].strip()

    name = frontmatter.get("name")
    description = frontmatter.get("description")
    if not name or not description:
        raise ValueError(f"❌ {path}: frontmatter requires 'name' and 'description'")

    tool_names = frontmatter.get("tools") or []
    unknown = [t for t in tool_names if t not in TOOL_REGISTRY]
    if unknown:
        raise ValueError(f"❌ {path}: unknown tools in frontmatter: {unknown}")

    context_loader = frontmatter.get("context_loader")
    if context_loader is not None and context_loader not in CONTEXT_LOADERS:
        raise ValueError(f"❌ {path}: unknown context_loader '{context_loader}'")

    return Skill(
        name=name,
        description=description,
        body=body,
        tool_names=tuple(tool_names),
        context_loader=context_loader,
        path=path,
    )


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

# Most values are tool objects; factory entries take the session's
# campaign_id (their tools close over that id).
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
    "campaign_negotiation_tools": build_campaign_negotiation_tools,
}

# Registry entries that are factories taking campaign_id rather than tools.
TOOL_FACTORIES = {"campaign_admin_tools", "campaign_negotiation_tools"}


def resolve_tools(skill: Skill, *, campaign_id: int | None = None) -> list:
    """Instantiate a skill's declared tools for one session."""
    tools: list = []
    for name in skill.tool_names:
        entry = TOOL_REGISTRY[name]
        if name in TOOL_FACTORIES:
            if campaign_id is None:
                raise ValueError(f"🛠️ Skill '{skill.name}' needs a campaign_id for its tools")
            tools.extend(entry(campaign_id))
        else:
            tools.append(entry)
    return tools


def resolve_skill_set_tools(skills: list[Skill], *, campaign_id: int | None = None) -> list:
    """Union of every skill's tools, deduplicated by tool name.

    create_agent requires all bindable tools to be registered at creation;
    the middleware then limits what the model *sees* per call to the active
    skills' subsets.
    """
    by_name: dict[str, Any] = {}
    for skill in skills:
        for tool in resolve_tools(skill, campaign_id=campaign_id):
            by_name.setdefault(tool.name, tool)
    return list(by_name.values())


# ---------------------------------------------------------------------------
# Context loaders
# ---------------------------------------------------------------------------


async def _load_lore_context(
    messages: list[AnyMessage], *, world_name: str | None = None, **_: Any
) -> str:
    """📋 The world's lore entry listing (ids + titles) from Postgres."""
    if world_name is None:
        logger.warning("⚠️ lore context loader called without a world_name")
        return "(no world bound to this session)"
    world_id = await asyncio.to_thread(knowledge.get_world_id, world_name)
    if world_id is None:
        logger.warning(f"⚠️ World '{world_name}' not found, starting with empty context")
        return "(world has no entries yet)"
    entries = await asyncio.to_thread(knowledge.list_entries, world_id)
    context = (
        "\n".join(f"- id={e['id']} | title='{e['title']}'" for e in entries)
        if entries
        else "(world has no entries yet)"
    )
    logger.info(f"🌍 Loaded {len(entries)} lore entries for world '{world_name}'")
    return context


async def _load_campaign_overview(
    messages: list[AnyMessage], *, campaign_id: int | None = None, **_: Any
) -> str:
    """📋 The campaign's current configuration, fresh from Postgres."""
    if campaign_id is None:
        logger.warning("⚠️ campaign_overview loader called without a campaign_id")
        return "(no campaign bound to this session)"
    overview = await asyncio.to_thread(render_campaign_overview, campaign_id)
    logger.info(f"📋 Loaded overview for campaign {campaign_id}")
    return overview


CONTEXT_LOADERS: dict[str, Any] = {
    "lore": _load_lore_context,
    "campaign_overview": _load_campaign_overview,
}

# Maps a loader key to the template variable its output fills in skill bodies.
LOADER_TEMPLATE_VARS = {
    "lore": "existing_lore_context",
    "campaign_overview": "campaign_context",
}


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class SkillRegistry:
    """Discovers and serves every SKILL.md under the skills root."""

    def __init__(self, root: Path = SKILLS_ROOT) -> None:
        self.root = root
        self._skills: dict[str, Skill] = {}
        self._scan()

    def _scan(self) -> None:
        if not self.root.is_dir():
            logger.warning(f"⚠️ Skills root '{self.root}' does not exist; no skills loaded")
            return
        for path in sorted(self.root.glob("*/SKILL.md")):
            skill = parse_skill_md(path)
            self._skills[skill.name] = skill
            logger.debug(f"📚 Registered skill '{skill.name}' from {path}")
        logger.info(f"📚 Skill registry: {len(self._skills)} skill(s) from '{self.root}'")

    def get(self, name: str) -> Skill:
        try:
            return self._skills[name]
        except KeyError:
            available = ", ".join(sorted(self._skills)) or "(none)"
            raise KeyError(f"❌ Unknown skill '{name}'. Available: {available}") from None

    def names(self) -> list[str]:
        return sorted(self._skills)

    def metadata_listing(self, names: list[str]) -> str:
        """Layer-1 progressive disclosure: name + description only."""
        return "\n".join(f"- {s.name}: {s.description}" for s in (self.get(n) for n in names))

    def render(self, name: str) -> ChatPromptTemplate:
        """Build a ChatPromptTemplate from a skill body (system message) plus a
        ``messages`` placeholder -- a drop-in replacement for the Langfuse
        prompt templates used by the hand-built DM graph nodes."""
        return ChatPromptTemplate.from_messages([
            ("system", self.get(name).body),
            MessagesPlaceholder("messages"),
        ])


skill_registry = SkillRegistry()
