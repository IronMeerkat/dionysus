from logging import getLogger
from typing import Annotated
import operator
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, AnyMessage
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from hephaestus.helpers import Oligaton

from database.graphiti_utils import load_information, make_group_id, make_memory_group_id, fire_and_forget, process_and_save_memory
from database.models import Character as CharacterModel
from database.models.conversation import Conversation
from utils.llm_models import npc_emotions, npc_should_respond, npc_thoughts, npc_narration
from utils.prompts import plan_prompt_template, narrator_prompt_template, emotions_prompt_template, should_respond_prompt_template, character_episodic_memory

logger = getLogger(__name__)

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

    emotional_state_model = npc_emotions.with_structured_output(EmotionalState.model_json_schema(), strict=True)

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
        decision_model = npc_should_respond.with_structured_output(ShouldRespondDecision, strict=True, include_raw=True)
        raw_result: dict = await decision_model.ainvoke(prompt)
        parsing_error = raw_result.get("parsing_error")
        if parsing_error:
            logger.error(f"💥 {character.name} structured output parsing failed: {parsing_error}")
            logger.debug(f"💥 Raw response: {raw_result.get('raw')}")
            return END
        response: ShouldRespondDecision = raw_result["parsed"]
        if response is None:
            logger.error(f"💥 {character.name} structured output parsed=None (no parsing_error). Raw: {raw_result.get('raw')}")
            return END
        if response.should_respond:
            logger.info(f"✅ {character.name} decided to respond")
            return ["lore_loader", "memories_loader"]
        logger.info(f"🚫 {character.name} decided NOT to respond")
        return END

    async def lore_loader(state: NPCState) -> NPCState:
        last_human_message = next(m for m in reversed(state.messages) if isinstance(m, HumanMessage))
        lore = await load_information(
            query=last_human_message.content,
            group_ids=[make_group_id("lore", conversation.campaign.lore_world)],
        )

        return {'lore': lore, 'messages': []}

    async def memories_loader(state: NPCState) -> NPCState:
        last_human_message = next(m for m in reversed(state.messages) if isinstance(m, HumanMessage))
        memories = await load_information(
            query=last_human_message.content,
            group_ids=[
                make_memory_group_id(conversation.campaign.id, character.name),
                # make_group_id("lore", conversation.campaign.lore_world),
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

        thoughts = await npc_thoughts.ainvoke(prompt)
        if thoughts.content is None:
            logger.warning("🧠 Planner returned None, using empty Thoughts")

        tagged = f"## {character.name} THOUGHTS:\n{thoughts.content}"
        logger.info(f"🧠 Planner response: {tagged[:min(200, len(tagged))]}...")
        return {'thoughts': tagged, 'messages': []}


    async def npc_narrator(state: NPCState) -> NPCState:

        prompt = await narrator_prompt_template.ainvoke(state.combined_dump)
        prompt.messages.append(AIMessage(content=f"{character.name}:"))

        response = await npc_narration.ainvoke(prompt)

        content = response.content.strip()
        prefix = f"{character.name}:"
        if content.startswith(prefix):
            content = content[len(prefix):].lstrip()
        response.content = f"{character.name}: {content}"

        response.name = character.name
        response.id = str(uuid4())
        fire_and_forget(process_and_save_memory(
            messages=state.combined_messages,
            group_id=make_memory_group_id(conversation.campaign.id, character.name),
            source_description=f"session:{conversation.campaign.lore_world}",
            perspective=character_episodic_memory.compile(name=character.name, description=character.description),
            character_name=character.name,
            character_description=character.description,
        ))
        return {'messages': [response]}

    graph = StateGraph(NPCState)
    graph.add_node("lore_loader", lore_loader)
    graph.add_node("memories_loader", memories_loader)
    graph.add_node("emotion_updater", emotion_updater)
    graph.add_node("planner", planner)

    graph.add_node("npc_narrator", npc_narrator)
    graph.add_conditional_edges(START, should_respond)
    graph.add_edge(["lore_loader", "memories_loader"], "emotion_updater")
    graph.add_edge("emotion_updater", "planner")

    graph.add_edge("planner", "npc_narrator")
    graph.add_edge("npc_narrator", END)

    return graph.compile(name=character.name)


def spawn_npc_directed(
    character: CharacterModel,
    conversation: Conversation,
    directive: object,
) -> StateGraph:
    """Build an NPC graph that skips should_respond and accepts DM directives.

    The DM has already decided this NPC should speak. The ``directive``
    object provides ``.guidance`` (what to focus on) and ``.withheld_info``
    (facts to avoid revealing).
    """

    dm_guidance: str = getattr(directive, "guidance", "")
    withheld_info: list[str] = getattr(directive, "withheld_info", [])

    other_characters = [
        f"**{c.name}**:\n{c.description}"
        for c in conversation.characters
        if c.id != character.id
    ]
    other_characters_str = "\n\n\n".join(other_characters)

    emotional_state_model = npc_emotions.with_structured_output(
        EmotionalState.model_json_schema(), strict=True
    )
    emotional_state = EmotionalState(_key=character.name)

    withheld_block = ""
    if withheld_info:
        withheld_block = (
            "\n[INFORMATION YOU DO NOT KNOW - never reference these facts]\n"
            + "\n".join(f"- {fact}" for fact in withheld_info)
        )

    class DirectedNPCState(BaseModel):
        messages: Annotated[list[AnyMessage], operator.add]
        thoughts: str = Field(default="")
        lore: str = Field(default="")
        memories: str = Field(default="")

        @property
        def combined_messages(self) -> list[AnyMessage]:
            combo = [*conversation.message_buffer, *self.messages]
            limit = min(12, len(combo))
            return combo[-limit:]

        @property
        def emotional_state(self) -> str:
            raw = emotional_state.model_dump(exclude_unset=True)
            return "\n".join(f"{k}: {v}" for k, v in raw.items())

        @property
        def combined_dump(self) -> dict:
            return {
                "name": character.name,
                "description": character.description + withheld_block,
                "other_characters": other_characters_str,
                "player": conversation.player.description,
                "location": conversation.location,
                "story_background": conversation.story_background,
                "messages": self.combined_messages,
                "emotional_state": self.emotional_state,
                "dm_guidance": dm_guidance,
                **self.model_dump(exclude={"messages"}),
            }

    async def lore_loader(state: DirectedNPCState) -> DirectedNPCState:
        last_human = next(
            (m for m in reversed(state.messages) if isinstance(m, HumanMessage)),
            None,
        )
        query = last_human.content if last_human else character.name
        lore = await load_information(
            query=query,
            group_ids=[make_group_id("lore", conversation.campaign.lore_world)],
        )
        return {"lore": lore, "messages": []}

    async def memories_loader(state: DirectedNPCState) -> DirectedNPCState:
        last_human = next(
            (m for m in reversed(state.messages) if isinstance(m, HumanMessage)),
            None,
        )
        query = last_human.content if last_human else character.name
        memories = await load_information(
            query=query,
            group_ids=[
                make_memory_group_id(conversation.campaign.id, character.name),
            ],
            limit=20,
        )
        return {"memories": memories, "messages": []}

    async def emotion_updater(state: DirectedNPCState) -> DirectedNPCState:
        prompt = await emotions_prompt_template.ainvoke(state.combined_dump)
        logger.debug(f"💖 Emotion updater prompt built for {character.name}")

        delta = await emotional_state_model.ainvoke(prompt)
        logger.info(f"💖 Emotion delta for {character.name}: {delta}")

        for field_name, value in delta.items():
            current_value = getattr(emotional_state, field_name)
            new_value = max(-20, min(20, current_value + value))
            setattr(emotional_state, field_name, new_value)

        return {"messages": []}

    async def planner(state: DirectedNPCState) -> DirectedNPCState:
        prompt = await plan_prompt_template.ainvoke({
            **state.combined_dump,
            "emotional_state": state.emotional_state,
        })
        logger.debug(f"🧠 Directed planner prompt for {character.name}")

        thoughts = await npc_thoughts.ainvoke(prompt)
        if thoughts.content is None:
            logger.warning(f"🧠 {character.name} planner returned None")

        tagged = f"## {character.name} THOUGHTS:\n{thoughts.content}"
        logger.info(f"🧠 {character.name}: {tagged[:min(200, len(tagged))]}...")
        return {"thoughts": tagged, "messages": []}

    async def npc_narrator(state: DirectedNPCState) -> DirectedNPCState:
        prompt = await narrator_prompt_template.ainvoke(state.combined_dump)
        prompt.messages.append(AIMessage(content=f"{character.name}:"))

        response = await npc_narration.ainvoke(prompt)

        content = response.content.strip()
        prefix = f"{character.name}:"
        if content.startswith(prefix):
            content = content[len(prefix):].lstrip()
        response.content = f"{character.name}: {content}"

        response.name = character.name
        response.id = str(uuid4())
        fire_and_forget(process_and_save_memory(
            messages=state.combined_messages,
            group_id=make_memory_group_id(conversation.campaign.id, character.name),
            source_description=f"session:{conversation.campaign.lore_world}",
            perspective=character_episodic_memory.compile(
                name=character.name, description=character.description
            ),
            character_name=character.name,
            character_description=character.description,
        ))
        return {"messages": [response]}

    graph = StateGraph(DirectedNPCState)
    graph.add_node("lore_loader", lore_loader)
    graph.add_node("memories_loader", memories_loader)
    graph.add_node("emotion_updater", emotion_updater)
    graph.add_node("planner", planner)
    graph.add_node("npc_narrator", npc_narrator)

    graph.add_edge(START, "lore_loader")
    graph.add_edge(START, "memories_loader")
    graph.add_edge(["lore_loader", "memories_loader"], "emotion_updater")
    graph.add_edge("emotion_updater", "planner")
    graph.add_edge("planner", "npc_narrator")
    graph.add_edge("npc_narrator", END)

    return graph.compile(name=character.name)