"""🔧 Chat services: load participants and build agent swarm."""
from agents.agent_swarm import create_agent_swarm
from agents.nonplayer import spawn_npc
from database.models import Character, Player
from database.postgres_connection import session


def load_participants():
    players = session.query(Player.id, Player.name).order_by(Player.id.asc()).all()
    characters = session.query(Character.id, Character.name).order_by(Character.id.asc()).all()
    return players, characters


def build_swarm(player, selected_characters):
    agent_specs = []
    graph_node_to_character_name = {}
    for character in selected_characters:
        char_agent = spawn_npc(character.name, character.description, player.description)
        graph_node = f"character_{character.id}"
        agent_specs.append((graph_node, char_agent))
        graph_node_to_character_name[graph_node] = character.name
        graph_node_to_character_name[character.name] = character.name
    swarm = create_agent_swarm(*agent_specs)
    if len(selected_characters) == 1:
        graph_node_to_character_name["npc_narrator"] = selected_characters[0].name
    return swarm, graph_node_to_character_name
