"""🤖 One skill-driven tool agent, replacing the per-role tool-loop subagents.

A single ``create_agent`` whose persona, workflow, and toolset come from
SKILL.md files (see ``agents/skills/``). Entry points declare which skills a
session can use and which are pre-activated; the agent can activate the rest
on demand via the middleware-provided ``load_skill`` tool.
"""
from langchain.agents import create_agent

from agents.skills.middleware import RetryMiddleware, SkillsMiddleware
from utils.llm_models import skilled_agent_model

# Skills available to world-scoped sessions (lore library UI, NPC builder UI,
# and the DM's build loop).
WORLD_SKILLS = ["lore-management", "npc-building"]


def spawn_skilled_agent(
    skills: list[str],
    *,
    active: list[str] | None = None,
    world_name: str | None = None,
    campaign_id: int | None = None,
    name: str = "skilled_agent",
):
    """Build a multi-turn conversational agent driven by skills.

    Stateless per invocation: callers pass the full conversation history each
    time, matching the spawn_* functions this replaces.
    """
    skills_middleware = SkillsMiddleware(
        skills,
        active=active,
        world_name=world_name,
        campaign_id=campaign_id,
    )
    return create_agent(
        model=skilled_agent_model,
        # create_agent only executes tools registered up front; the middleware
        # binds just the active skills' subsets per model call.
        tools=skills_middleware.registered_tools(),
        middleware=[skills_middleware, RetryMiddleware(name=name)],
        name=name,
    )
