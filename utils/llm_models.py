import copy
from typing import Any

from langchain_xai import ChatXAI

from hephaestus.settings import settings

from utils.nanogpt_integration import ChatNanoGPT

models = settings.models


glm = models.glm.model_dump()
moonshot = models.moonshot.model_dump()
small_glm = models.small_glm.model_dump()

# def _nano(
#     *,
#     thinking_disabled: bool = False,
#     reasoning_effort: str | None = None,
#     max_tokens: int | None = None,
# ) -> dict[str, Any]:
#     """🪙 Build a tuned nanogpt config for simple/cheap hops.

#     GLM-5.2 defaults to *unbounded* reasoning, which is a costly 7-minute trap
#     for trivial work. Pass ``thinking_disabled=True`` to skip thinking entirely
#     (pure classification/detection), or ``reasoning_effort`` to cap it at the
#     cheapest enabled level. ``max_tokens`` caps the response budget.
#     """
#     cfg = copy.deepcopy(nanogpt)
#     extra = dict(cfg.get("extra_body", {}))
#     if thinking_disabled:
#         extra["thinking"] = {"type": "disabled"}
#     elif reasoning_effort is not None:
#         extra["thinking"] = {"type": "enabled"}
#         extra["reasoning_effort"] = reasoning_effort
#     cfg["extra_body"] = extra
#     if max_tokens is not None:
#         cfg["max_tokens"] = max_tokens
#     return cfg

npc_narration = ChatNanoGPT(**glm)
# npc_narration = ChatXAI(**models.xai)

scene_change = ChatNanoGPT(**moonshot) #ChatXAI(**xai, max_tokens=128)

# One model for every skill-driven tool agent (lore management, NPC building,
# campaign admin); the differentiating behavior lives in SKILL.md files.
skilled_agent_model = ChatNanoGPT(**moonshot) #ChatXAI(**xai, extra_body={"reasoning_effort": "high"})

# skilled_agent_model = ChatNanoGPT(
#     model="Qwen3.5-27B-BlueStar-Derestricted",
#     temperature=0.8,
#     presence_penalty=0.2,
#     max_retries=4,
# )

dm_planner_model = ChatNanoGPT(**moonshot) #ChatXAI(**xai, extra_body={"reasoning_effort": "high"}, max_tokens=2400)

# dm_narrator_model = ChatXAI(**models.xai)

dm_narrator_model = ChatNanoGPT(**glm)

# --- DM supervisor subagents ------------------------------------------------
# Fast non-reasoning model for cheap classification/validation hops.
dm_continuity_model = ChatNanoGPT(**moonshot) #ChatXAI(**xai_small)

dm_ooc_model = ChatNanoGPT(**glm) #ChatXAI(**xai)
dm_faction_model = ChatNanoGPT(**glm) #ChatXAI(**xai, extra_body={"reasoning_effort": "high"})