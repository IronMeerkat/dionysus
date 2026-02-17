from logging import getLogger
import chainlit as cl
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from hephaestus.logging import init_logger
init_logger()
from hephaestus.langfuse_handler import langfuse_callback_handler


from agents.agent_swarm import create_agent_swarm
from agents.nonplayer import spawn_npc
from assistant import stream_npc_assistant
from database.models import Character, Conversation, Player
from database.postgres_connection import session

logger = getLogger(__name__)


def _render_character_selection(characters: list[Character], selected_ids: set[int]) -> str:
    selected_names = [c.name for c in characters if c.id in selected_ids]
    selected_line = ", ".join(selected_names) if selected_names else "None yet"
    return (
        "🎭 Pick characters for this conversation.\n"
        "Click a character to toggle selection, then click Done.\n\n"
        f"Selected: {selected_line}"
    )


def _load_available_participants() -> tuple[list[Player], list[Character]]:
    players = session.query(Player.id, Player.name).order_by(Player.id.asc()).all()
    characters = session.query(Character.id, Character.name).order_by(Character.id.asc()).all()
    return players, characters


async def _ask_player(players: list[Player]) -> Player:
    actions = [
        cl.Action(
            name=f"pick_player_{player.id}",
            payload={"player_id": player.id},
            label=f"🎮 {player.name}",
        )
        for player in players
    ]
    response = await cl.AskActionMessage(
        content="🎮 Choose a player to begin a new conversation.",
        actions=actions,
        timeout=300,
        raise_on_timeout=True,
    ).send()
    if not response:
        raise RuntimeError("No player selection response received.")

    player_id = response['payload']['player_id']

    selected_player = session.query(Player).filter(Player.id == player_id).first()
    if selected_player is None:
        raise ValueError(f"Selected player id {player_id} not found.")
    return selected_player


async def _ask_characters(characters: list[Character]) -> list[Character]:
    selected_ids: set[int] = set()
    characters_by_id = {character.id: character for character in characters}

    while True:
        toggle_actions = [
            cl.Action(
                name=f"toggle_character_{character.id}",
                payload={"character_id": character.id},
                label=(
                    f"{'✅' if character.id in selected_ids else '➕'} "
                    f"{character.name}"
                ),
            )
            for character in characters
        ]
        done_action = cl.Action(
            name="character_selection_done",
            payload={"action": "done"},
            label="✅ Done",
        )

        response = await cl.AskActionMessage(
            content=_render_character_selection(characters, selected_ids),
            actions=[*toggle_actions, done_action],
            timeout=300,
            raise_on_timeout=True,
        ).send()
        if not response:
            raise RuntimeError("No character selection response received.")

        payload = response['payload']
        if payload.get("action") == "done":
            if selected_ids:
                break
            logger.warning("⚠️ Done clicked with no character selected.")
            await cl.Message(
                content="⚠️ Pick at least one character before continuing."
            ).send()
            continue

        character_id = payload.get('character_id')
        if character_id not in characters_by_id:
            raise ValueError(f"Selected character id {character_id} not found.")

        if character_id in selected_ids:
            selected_ids.remove(character_id)
            logger.info(f"➖ Deselected character id={character_id}")
        else:
            selected_ids.add(character_id)
            logger.info(f"➕ Selected character id={character_id}")

    return session.query(Character).filter(Character.id.in_(selected_ids)).all()


def _build_swarm_for_characters(
    player: Player,
    selected_characters: list[Character],
) -> tuple[object, dict[str, str]]:
    agent_specs: list[tuple[str, object]] = []
    graph_node_to_character_name: dict[str, str] = {}

    for character in selected_characters:
        char_agent = spawn_npc(
            character.name,
            character.description ,
            player.description,
        )
        # Stable node ID for attribution in nested graph metadata.
        graph_node = f"character_{character.id}"
        agent_specs.append((graph_node, char_agent))
        graph_node_to_character_name[graph_node] = character.name
        # Single-agent flows can still expose compiled graph name.
        graph_node_to_character_name[character.name] = character.name

    swarm = create_agent_swarm(*agent_specs)
    # Single-agent: narrator node may appear as path[-1] without parent; map it.
    if len(selected_characters) == 1:
        graph_node_to_character_name["npc_narrator"] = selected_characters[0].name
    return swarm, graph_node_to_character_name


@cl.on_chat_start
async def on_start():
    """
    🚀 Initialize the chat session via Chainlit AskActionMessage wizard.
    """
    try:
        players, characters = _load_available_participants()

        if not players:
            logger.warning("⚠️ No players found in database.")
            await cl.Message(
                content="⚠️ No players found. Please add players to the database first."
            ).send()
            return

        if not characters:
            logger.warning("⚠️ No characters found in database.")
            await cl.Message(
                content="⚠️ No characters found. Please add characters to the database first."
            ).send()
            return

        player = await _ask_player(players)
        selected_characters = await _ask_characters(characters)

        conversation = Conversation.create(player, selected_characters)
        swarm, graph_node_to_character_name = _build_swarm_for_characters(
            player, selected_characters
        )

        character_name = ", ".join(c.name for c in selected_characters)
        character_ids = [c.id for c in selected_characters]

        cl.user_session.set("npc_agent", swarm)
        cl.user_session.set("message_history", [])
        cl.user_session.set("character_name", character_name)
        cl.user_session.set("conversation_id", conversation.id)
        cl.user_session.set("player_id", player.id)
        cl.user_session.set("character_ids", character_ids)
        cl.user_session.set("graph_node_to_character_name", graph_node_to_character_name)

        character_list = character_name
        logger.info(
            f"🎬 Conversation {conversation.id} created: player={player.name}, "
            f"characters=[{character_list}]"
        )
        await cl.Message(
            content=(
                f"🎬 New conversation ready!\n"
                f"🎮 Player: **{player.name}**\n"
                f"🎭 Characters: **{character_list}**"
            )
        ).send()
    except TimeoutError as exc:
        logger.exception(f"⏰ Setup wizard timed out: {exc}")
        await cl.Message(
            content="⏰ Setup timed out. Please restart the chat to try again."
        ).send()
    except Exception as exc:
        logger.exception(f"❌ Failed to initialize chat session: {exc}")
        await cl.Message(
            content="❌ Failed to initialize conversation setup. Please restart chat."
        ).send()


@cl.on_message
async def on_message(cl_message: cl.Message):
    """
    💬 Handle incoming messages and get NPC response.
    """
    npc_agent = cl.user_session.get("npc_agent")
    character_name = cl.user_session.get("character_name")

    if not npc_agent:
        logger.error("❌ No NPC agent found in session!")
        await cl.Message(content="❌ Error: No character loaded. Please restart the chat.").send()
        return

    config = {"configurable": {"thread_id": cl.context.session.id}}
    callbacks = [cl.LangchainCallbackHandler(), langfuse_callback_handler]
    runnable_config = RunnableConfig(callbacks=callbacks, **config)

    stream = npc_agent.stream(
        {"messages": [HumanMessage(content=cl_message.content)]},
        stream_mode="messages",
        config=runnable_config,
    )
    await stream_npc_assistant(character_name, stream)
