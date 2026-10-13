from hephaestus.model_wrappers import ChatNanoGPT
from hephaestus.settings import settings

models = settings.models


glm = models.glm.model_dump()
moonshot = models.moonshot.model_dump()
small_glm = models.small_glm.model_dump()



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