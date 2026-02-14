from langgraph.graph import StateGraph
from pydantic import BaseModel
from typing import Annotated
from langchain_core.messages import AnyMessage
import operator
from langgraph.graph import START, END


def _resolve_agent(item: object) -> tuple[str, object]:
    """Resolve (name, agent) or agent to (name, runnable)."""
    if isinstance(item, tuple) and len(item) == 2:
        return (str(item[0]), item[1])
    agent = item
    name = getattr(agent, "name", "agent")
    return (name, agent)


def create_agent_swarm(*agents: StateGraph | tuple[str, object]) -> object:
    """
    Create a swarm from one or more agents.
    Each agent can be a StateGraph/Runnable or a (name, agent) tuple.
    Single-agent swarm returns the agent directly (no wrapper) for correct stream metadata.
    """
    resolved = [_resolve_agent(a) for a in agents]

    if len(resolved) == 1:
        _, agent = resolved[0]
        return agent

    class AgentSwarmState(BaseModel):
        messages: Annotated[list[AnyMessage], operator.add]

    graph = StateGraph[AgentSwarmState, None, AgentSwarmState, AgentSwarmState](AgentSwarmState)

    for name, agent in resolved:
        graph.add_node(name, agent)

    node_names = [START, *[n for n, _ in resolved], END]

    for agent_name, next_agent_name in zip(node_names, node_names[1:]):
        graph.add_edge(agent_name, next_agent_name)

    return graph.compile()