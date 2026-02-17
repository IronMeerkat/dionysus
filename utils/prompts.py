from langchain_core.prompts import ChatPromptTemplate

from hephaestus.langfuse_handler import langfuse


def get_langchain_prompt(prompt_name: str) -> ChatPromptTemplate:

    return ChatPromptTemplate.from_messages(
        langfuse.get_prompt(prompt_name).get_langchain_prompt())

plan_prompt_template = get_langchain_prompt("npc-plan")
tool_prompt_template = get_langchain_prompt("npc-tool")
narrator_prompt_template = get_langchain_prompt("npc-narrator")
