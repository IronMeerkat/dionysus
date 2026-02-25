from langchain_core.prompts import ChatPromptTemplate

from hephaestus.langfuse_handler import langfuse


def get_langchain_prompt(prompt_name: str) -> ChatPromptTemplate:

    return ChatPromptTemplate.from_messages(
        langfuse.get_prompt(prompt_name).get_langchain_prompt())

plan_prompt_template = get_langchain_prompt("npc-plan")
tool_prompt_template = get_langchain_prompt("npc-tool")
narrator_prompt_template = get_langchain_prompt("npc-narrator")
emotions_prompt_template = get_langchain_prompt("npc-emotions")

npc_creator_prompt_template = get_langchain_prompt("npc-creator")

scene_change_prompt_template = get_langchain_prompt("did-scene-change")
character_episodic_memory = langfuse.get_prompt("character-episodic-memory")

should_respond_prompt_template = get_langchain_prompt("should-respond")

placeholder_location = langfuse.get_prompt("placeholder_location").prompt
placeholder_scenario = langfuse.get_prompt("placeholder_scenario").prompt