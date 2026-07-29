from langchain_core.prompts import ChatPromptTemplate

from hephaestus.langfuse_handler import langfuse


def get_langchain_prompt(prompt_name: str) -> ChatPromptTemplate:

    return ChatPromptTemplate.from_messages(
        langfuse.get_prompt(prompt_name).get_langchain_prompt())

narrator_prompt_template = get_langchain_prompt("npc-narrator")

memory_significance_prompt = get_langchain_prompt("memory-significance-filter")

dm_planner_prompt_template = get_langchain_prompt("dm-planner")
dm_narrator_prompt_template = get_langchain_prompt("dm-narrator")
dm_npc_reviewer_prompt_template = get_langchain_prompt("dm-npc-reviewer")

dm_ooc_responder_prompt_template = get_langchain_prompt("dm-ooc-responder")
dm_faction_prompt_template = get_langchain_prompt("dm-faction-simulator")
dm_scene_summarizer_prompt_template = get_langchain_prompt("dm-scene-summarizer")

placeholder_location = langfuse.get_prompt("placeholder_location").prompt
placeholder_scenario = langfuse.get_prompt("placeholder_scenario").prompt
