from langchain_xai import ChatXAI

from utils.nanogpt_integration import ChatNanoGPT

npc_manager = ChatXAI(
    model="grok-4-1-fast-reasoning", 
    temperature=0.8, 
    max_retries=3,
)


npc_emotions = ChatXAI(
    model="grok-4-1-fast-non-reasoning", 
    temperature=0.3, 
    max_retries=4,
)

npc_should_respond = ChatXAI(
    model="grok-4-1-fast-non-reasoning", 
    temperature=0.0, 
    max_retries=4,
)
# npc_thoughts = ChatXAI(
#     model="grok-4.20-beta-0309-reasoning", 
#     temperature=0.8, 
#     max_tokens=1024, 
#     max_retries=4,
# )

npc_thoughts = ChatNanoGPT(
    model="GLM-4.5-Air-Derestricted-Iceblink-v2", 
    temperature=0.5, 
    max_tokens=16000,
    max_retries=4,
    frequency_penalty=0.4,
)
# npc_narration = ChatXAI(
#     model="grok-4.20-beta-0309-reasoning", 
#     top_p=1, 
#     max_retries=4,
# )

npc_narration = ChatNanoGPT(
    model="Llama-3.3-70B-Forgotten-Abomination-v5.0", 
    temperature=0.8, 
    presence_penalty=0.2,
    max_retries=4,
)

scene_change = ChatXAI(
    model="grok-4-1-fast", 
    temperature=0, 
    max_tokens=128, 
    max_retries=3,
)

# lore_creator = ChatXAI(
#     model="grok-4-1-fast-reasoning",
#     temperature=0.7,
#     max_retries=3,
# )

lore_creator = ChatNanoGPT(
    model="Qwen3.5-27B-BlueStar-Derestricted", 
    temperature=0.8, 
    presence_penalty=0.2,
    max_retries=4,
)