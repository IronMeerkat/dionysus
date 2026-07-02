from langchain_xai import ChatXAI

from hephaestus.settings import settings

from utils.nanogpt_integration import ChatNanoGPT

models = settings.models

xai = models.xai.model_dump()
xai_small = models.xai_small.model_dump()
nanogpt = models.nanogpt.model_dump()

npc_emotions = ChatNanoGPT(**nanogpt) #ChatXAI(**xai)
npc_thoughts = ChatNanoGPT(**nanogpt) #ChatXAI(**xai, extra_body={"reasoning_effort": "high"}, max_tokens=2400)
npc_narration = ChatNanoGPT(**nanogpt)
# npc_narration = ChatXAI(**models.xai)

scene_change = ChatNanoGPT(**nanogpt) #ChatXAI(**xai, max_tokens=128)

lore_creator = ChatNanoGPT(**nanogpt) #ChatXAI(**xai, extra_body={"reasoning_effort": "high"})

# lore_creator = ChatNanoGPT(
#     model="Qwen3.5-27B-BlueStar-Derestricted",
#     temperature=0.8,
#     presence_penalty=0.2,
#     max_retries=4,
# )

memory_filter = ChatNanoGPT(**nanogpt) #ChatXAI(**xai)

npc_builder = ChatNanoGPT(**nanogpt) #ChatXAI(**xai, extra_body={"reasoning_effort": "high"})

# --- Campaign Admin (out-of-character campaign configuration chat) ---
campaign_admin = ChatNanoGPT(**nanogpt) #ChatXAI(**xai, extra_body={"reasoning_effort": "high"})


dm_planner_model = ChatNanoGPT(**nanogpt) #ChatXAI(**xai, extra_body={"reasoning_effort": "high"}, max_tokens=2400)

# dm_narrator_model = ChatXAI(**models.xai)

dm_narrator_model = ChatNanoGPT(**nanogpt)

# --- DM supervisor subagents ------------------------------------------------
# Fast non-reasoning model for cheap classification/validation hops.
dm_intent_model = ChatNanoGPT(**nanogpt) #ChatXAI(**xai_small)
dm_continuity_model = ChatNanoGPT(**nanogpt) #ChatXAI(**xai_small)

dm_referee_model = ChatNanoGPT(**nanogpt) #ChatXAI(**xai)
dm_ooc_model = ChatNanoGPT(**nanogpt) #ChatXAI(**xai)
dm_summarizer_model = ChatNanoGPT(**nanogpt) #ChatXAI(**xai)
dm_faction_model = ChatNanoGPT(**nanogpt) #ChatXAI(**xai, extra_body={"reasoning_effort": "high"})