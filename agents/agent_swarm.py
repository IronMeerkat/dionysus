from langgraph.graph import StateGraph
from pydantic import BaseModel
from typing import Annotated
from langchain_core.messages import AnyMessage
import operator
from langgraph.graph import START, END


def create_agent_swarm(*agents: StateGraph) -> StateGraph:

    class AgentSwarmState(BaseModel):
        messages: Annotated[list[AnyMessage], operator.add]

    graph = StateGraph[AgentSwarmState, None, AgentSwarmState, AgentSwarmState](AgentSwarmState)

    for agent in agents:
        graph.add_node(agent.name, agent)

    node_names = [START, *[a.name for a in agents], END]

    for agent_name, next_agent_name in zip(node_names, node_names[1:]):
        graph.add_edge(agent_name, next_agent_name)

    return graph.compile()