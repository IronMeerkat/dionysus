from langchain_core.prompts import ChatPromptTemplate

from hephaestus.langfuse_handler import langfuse


def get_langchain_prompt(prompt_name: str) -> ChatPromptTemplate:

    return ChatPromptTemplate.from_messages(
        langfuse.get_prompt(prompt_name).get_langchain_prompt())

plan_prompt_template = get_langchain_prompt("npc-plan")
tool_prompt_template = get_langchain_prompt("npc-tool")
narrator_prompt_template = get_langchain_prompt("npc-narrator")
emotions_prompt_template = get_langchain_prompt("npc-emotions")

scene_change_prompt_template = get_langchain_prompt("did-scene-change")
character_episodic_memory = langfuse.get_prompt("character-episodic-memory")

lore_creator_prompt_template = get_langchain_prompt("lore-creator")

memory_significance_prompt = get_langchain_prompt("memory-significance-filter")

npc_builder_prompt_template = get_langchain_prompt("npc-builder")

dm_planner_prompt_template = get_langchain_prompt("dm-planner")
dm_narrator_prompt_template = get_langchain_prompt("dm-narrator")
dm_npc_reviewer_prompt_template = get_langchain_prompt("dm-npc-reviewer")

dm_intent_router_prompt_template = get_langchain_prompt("dm-intent-router")
dm_rules_referee_prompt_template = get_langchain_prompt("dm-rules-referee")
dm_continuity_prompt_template = get_langchain_prompt("dm-continuity-checker")
dm_ooc_responder_prompt_template = get_langchain_prompt("dm-ooc-responder")
dm_faction_prompt_template = get_langchain_prompt("dm-faction-simulator")
dm_scene_summarizer_prompt_template = get_langchain_prompt("dm-scene-summarizer")

placeholder_location = langfuse.get_prompt("placeholder_location").prompt
placeholder_scenario = langfuse.get_prompt("placeholder_scenario").prompt

campaign_admin_prompt_template = get_langchain_prompt("campaign-admin")