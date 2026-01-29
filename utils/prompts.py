from langchain_core.prompts import ChatPromptTemplate

from hephaestus.langfuse_handler import langfuse


def get_langchain_prompt(prompt_name: str) -> ChatPromptTemplate:

    return ChatPromptTemplate.from_messages(
        langfuse.get_prompt(prompt_name).get_langchain_prompt())

def get_prompt_as_string(prompt_name: str) -> str:
    return langfuse.get_prompt(prompt_name).prompt

plan_prompt_template = get_langchain_prompt("npc-plan")
tool_prompt_template = get_langchain_prompt("npc-tool")
narrator_prompt_template = get_langchain_prompt("npc-narrator")

player_prompt = get_prompt_as_string("player.cornelius")
npc_prompt = get_prompt_as_string("npc.xaria")