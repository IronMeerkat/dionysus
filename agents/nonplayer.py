from logging import getLogger
from typing import Annotated
import operator
from uuid import uuid4

from langchain_core.messages import HumanMessage, AnyMessage
from langchain_xai import ChatXAI
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from hephaestus.helpers import Oligaton

from database.graphiti_utils import load_information, make_group_id, insert_information
from database.models import Character as CharacterModel
from database.models.conversation import Conversation
from tools.dice import roll_d20, roll_d10, roll_d6
from utils.prompts import plan_prompt_template, narrator_prompt_template, emotions_prompt_template, should_respond_prompt_template, character_episodic_memory

logger = getLogger(__name__)




def get_model(model: str = "grok-4-1-fast-reasoning", temperature: float = 1, max_retries: int = 3,**kwargs) -> ChatXAI:
    return ChatXAI(model=model, temperature=temperature, max_retries=max_retries, **kwargs)

model = get_model()
tools = [roll_d20, roll_d10, roll_d6]
tools_by_name = {tool.name: tool for tool in tools}

class ShouldRespondDecision(BaseModel):
    should_respond: bool = Field(description="Whether the NPC should respond to the current message.")

class EmotionalState(BaseModel, metaclass=Oligaton):
    love: int = Field(default=0, ge=-20, le=20, description="Intensity of affectionate attachment.")
    hate: int = Field(default=0, ge=-20, le=20, description="Intensity of hostile aversion.")
    fear: int = Field(default=0, ge=-20, le=20, description="Intensity of perceived threat or dread.")
    joy: int = Field(default=0, ge=-20, le=20, description="Intensity of happiness or delight.")
    sadness: int = Field(default=0, ge=-20, le=20, description="Intensity of sorrow or grief.")
    hope: int = Field(default=0, ge=-20, le=20, description="Intensity of positive expectation for outcomes.")


def spawn_npc(character: CharacterModel, conversation: Conversation) -> StateGraph:

    other_characters = [f"**{c.name}**:\n{c.description}" 
                        for c in conversation.characters 
                        if c.id != character.id]

    other_characters = '\n\n\n'.join(other_characters)

    emotional_state_model = get_model(model= "grok-4-1-fast-non-reasoning", temperature=0.3).with_structured_output(EmotionalState.model_json_schema(), strict=True)

    emotional_state = EmotionalState(_key=character.name)
    class NPCState(BaseModel):
        messages: Annotated[list[AnyMessage], operator.add]
        thoughts: str = Field(default='') 
        lore: str = Field(default='')
        memories: str = Field(default='')

        @property
        def combined_messages(self) -> list[AnyMessage]:
            combo = [*conversation.message_buffer, *self.messages]
            limit = min(12, len(combo))
            return combo[-limit:]

        @property
        def emotional_state(self) -> str:
            raw = emotional_state.model_dump(exclude_unset=True)
            return '\n'.join(f"{k}: {v}" for k, v in raw.items())

        @property
        def combined_dump(self) -> dict:
            return {
                'name': character.name,
                'description': character.description,
                'other_characters': other_characters,
                'player': conversation.player.description,
                'location': conversation.location,
                'story_background': conversation.story_background,
                'messages': self.combined_messages,
                'emotional_state': self.emotional_state,
                **self.model_dump(exclude={'messages'}),
            }
    
    async def should_respond(state: NPCState):
        prompt = await should_respond_prompt_template.ainvoke({
            "name": character.name,
            "description": character.description,
            "messages": state.combined_messages})
        decision_model = get_model(temperature=0.1).with_structured_output(ShouldRespondDecision)
        response = await decision_model.ainvoke(prompt)
        if response.should_respond:
            logger.info(f"✅ {character.name} decided to respond")
            # return ["lore_loader", "memories_loader"]
            return ["memories_loader"]
        logger.info(f"🚫 {character.name} decided NOT to respond")
        return END

    # async def lore_loader(state: NPCState) -> NPCState:
    #     last_human_message = next(m for m in reversed(state.messages) if isinstance(m, HumanMessage))
    #     lore = await load_information(
    #         query=last_human_message.content,
    #         group_ids=[make_group_id("lore", conversation.lore_world)],
    #     )

    #     return {'lore': lore, 'messages': []}

    async def memories_loader(state: NPCState) -> NPCState:
        last_human_message = next(m for m in reversed(state.messages) if isinstance(m, HumanMessage))
        memories = await load_information(
            query=last_human_message.content,
            group_ids=[
                make_group_id("memories", character.name),
                make_group_id("lore", conversation.lore_world),
            ],
            limit=20,
        )

        return {'memories': memories, 'messages': []}

    async def emotion_updater(state: NPCState) -> NPCState:
        prompt = await emotions_prompt_template.ainvoke(state.combined_dump)
        logger.debug(f"💖 Emotion updater prompt built for {character.name}")

        delta = await emotional_state_model.ainvoke(prompt)
        logger.info(f"💖 Emotion delta for {character.name}: {delta}")

        for field_name, value in delta.items():
            current_value = getattr(emotional_state, field_name)
            new_value = max(-20, min(20, current_value + value))
            setattr(emotional_state, field_name, new_value)


        return {'messages': []}

    async def planner(state: NPCState) -> NPCState:

        prompt = await plan_prompt_template.ainvoke({
            **state.combined_dump,
            'emotional_state': state.emotional_state,
            })
        logger.debug(f"🧠 Planner prompt: {prompt}")

        thoughts = await get_model(top_p=0.95, temperature=0.8, max_tokens=1024).ainvoke(prompt)
        if thoughts.content is None:
            logger.warning("🧠 Planner returned None, using empty Thoughts")
        logger.info(f"🧠 Planner response: {thoughts.content[:min(200, len(thoughts.content))]}...")
        return {'thoughts': thoughts.content, 'messages': []}


    async def npc_narrator(state: NPCState) -> NPCState:

        prompt = await narrator_prompt_template.ainvoke(state.combined_dump)

        response = await get_model(top_p=1).ainvoke(prompt)
        # if not response.content.startswith(f"**{character.name}**: "):
        #     response.content = f"**{character.name}**: {response.content}"
        response.name = character.name
        response.id = str(uuid4())
        try:
            await insert_information(
                messages=state.combined_messages,
                group_id=make_group_id("memories", character.name),
                source_description=f"session:{conversation.lore_world}",
                perspective=character_episodic_memory.compile(name=character.name, description=character.description),
            )
        except Exception as e:
            logger.exception(f"❌ Error inserting information:")
        return {'messages': [response]}

    graph = StateGraph(NPCState)
    # graph.add_node("lore_loader", lore_loader)
    graph.add_node("memories_loader", memories_loader)
    graph.add_node("emotion_updater", emotion_updater)
    graph.add_node("planner", planner)

    graph.add_node("npc_narrator", npc_narrator)
    graph.add_conditional_edges(START, should_respond)
    # graph.add_edge(["lore_loader", "memories_loader"], "emotion_updater")
    graph.add_edge("memories_loader", "emotion_updater")
    graph.add_edge("emotion_updater", "planner")

    graph.add_edge("planner", "npc_narrator")
    graph.add_edge("npc_narrator", END)

    return graph.compile(name=character.name)