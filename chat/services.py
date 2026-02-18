"""🔧 Chat services: load participants and build agent swarm."""
from hephaestus.agent_architectures import create_daisy_chain

from agents.nonplayer import spawn_npc
from database.models import Character, Player
from database.postgres_connection import session


def load_participants():
    players = session.query(Player.id, Player.name).order_by(Player.id.asc()).all()
    characters = session.query(Character.id, Character.name).order_by(Character.id.asc()).all()
    return players, characters


def build_swarm(player, selected_characters):
    agents = []
    graph_node_to_character_name = {}
    for character in selected_characters:
        char_agent = spawn_npc(character, player)
        agents.append(char_agent)
        graph_node_to_character_name[character.name] = character.name
    swarm = create_daisy_chain(*agents, name="npc_swarm")
    # if len(selected_characters) == 1:
    #     graph_node_to_character_name["npc_narrator"] = selected_characters[0].name
    return swarm, graph_node_to_character_name
