"""🎮 Setup wizards: player and character selection via Chainlit AskActionMessage."""
from logging import getLogger

import chainlit as cl

from database.models import Character, Player
from database.postgres_connection import session

logger = getLogger(__name__)


def _render_character_selection(characters, selected_ids):
    selected_names = [c.name for c in characters if c.id in selected_ids]
    selected_line = ", ".join(selected_names) if selected_names else "None yet"
    return (
        "🎭 Pick characters for this conversation.\n"
        "Click a character to toggle selection, then click Done.\n\n"
        f"Selected: {selected_line}"
    )


async def ask_player(players):
    actions = [
        cl.Action(name=f"pick_player_{p.id}", payload={"player_id": p.id}, label=f"🎮 {p.name}")
        for p in players
    ]
    msg = cl.AskActionMessage(
        content="🎮 Choose a player to begin a new conversation.",
        actions=actions,
    )
    response = await msg.send()
    if not response:
        raise RuntimeError("No player selection response received.")
    await msg.remove()
    player_id = response["payload"]["player_id"]
    selected = session.query(Player).filter(Player.id == player_id).first()
    if selected is None:
        raise ValueError(f"Selected player id {player_id} not found.")
    return selected


async def ask_characters(characters):
    selected_ids = set()
    characters_by_id = {c.id: c for c in characters}
    while True:
        toggle_actions = [
            cl.Action(
                name=f"toggle_character_{c.id}",
                payload={"character_id": c.id},
                label=f"{'✅' if c.id in selected_ids else '➕'} {c.name}",
            )
            for c in characters
        ]
        done_action = cl.Action(name="character_selection_done", payload={"action": "done"}, label="✅ Done")
        msg = cl.AskActionMessage(
            content=_render_character_selection(characters, selected_ids),
            actions=[*toggle_actions, done_action],
        )
        response = await msg.send()
        if not response:
            raise RuntimeError("No character selection response received.")
        await msg.remove()
        payload = response["payload"]
        if payload.get("action") == "done":
            if selected_ids:
                break
            logger.warning("⚠️ Done clicked with no character selected.")
            await cl.Message(content="⚠️ Pick at least one character before continuing.").send()
            continue
        character_id = payload.get("character_id")
        if character_id not in characters_by_id:
            raise ValueError(f"Selected character id {character_id} not found.")
        if character_id in selected_ids:
            selected_ids.remove(character_id)
            logger.info(f"➖ Deselected character id={character_id}")
        else:
            selected_ids.add(character_id)
            logger.info(f"➕ Selected character id={character_id}")
    return session.query(Character).filter(Character.id.in_(selected_ids)).all()
