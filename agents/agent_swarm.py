import operator
from typing import Annotated

from langchain_core.messages import AnyMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from database.postgres_connection import checkpointer


class AgentSwarmState(BaseModel):
    """🐝 Shared state flowing through every node in an agent swarm."""

    messages: Annotated[list[AnyMessage], operator.add]


def _resolve_agent(item: object) -> tuple[str, object]:
    """Resolve (name, agent) or agent to (name, runnable)."""
    if isinstance(item, tuple) and len(item) == 2:
        return (str(item[0]), item[1])
    agent = item
    name = getattr(agent, "name", "agent")
    return (name, agent)


def _wrap_agent_return_delta(agent: object) -> object:
    """Wrap an agent so it returns only the messages it added (delta), not the full list.

    Child agents return their full accumulated messages. With operator.add, the swarm
    would concatenate that with its current state, duplicating all prior messages.
    This wrapper extracts only the new messages the agent produced.
    """

    def wrapper(state: AgentSwarmState, config: RunnableConfig | None = None) -> dict:
        state_dict = (
            state.model_dump() if hasattr(state, "model_dump") else dict(state)
        )
        input_messages = state_dict.get("messages", [])
        invoke_config = config if config is not None else {}
        result = agent.invoke(state_dict, invoke_config)
        result_dict = (
            result.model_dump() if hasattr(result, "model_dump") else dict(result)
        )
        output_messages = result_dict.get("messages", [])
        n = len(input_messages)
        delta = output_messages[n:] if n <= len(output_messages) else []
        return {"messages": delta}

    return wrapper


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

    graph = StateGraph[AgentSwarmState, None, AgentSwarmState, AgentSwarmState](AgentSwarmState)

    for name, agent in resolved:
        graph.add_node(name, _wrap_agent_return_delta(agent))

    node_names = [START, *[n for n, _ in resolved], END]

    for agent_name, next_agent_name in zip(node_names, node_names[1:]):
        graph.add_edge(agent_name, next_agent_name)

    return graph.compile()