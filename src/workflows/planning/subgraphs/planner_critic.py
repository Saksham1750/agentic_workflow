import logging
from typing import Annotated, TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages

from src.workflows.planning.agents.planner import planner_agent
from src.workflows.planning.agents.critic import critic_agent

logger = logging.getLogger(__name__)


class PlannerCriticState(TypedDict):
    project_id: str
    requirements_json: dict
    architecture_json: dict
    selected_patterns: list[dict]
    tasks: list[dict]
    task_validation: dict | None
    iteration_count: int
    max_iterations: int
    feedback: str | None


async def planner_node(state: dict) -> dict:
    feedback = state.get("feedback")
    tasks = state.get("tasks", [])

    result = await planner_agent.create_task_plan(state)

    if feedback and tasks:
        result["tasks"] = tasks

    return result


async def critic_node(state: dict) -> dict:
    result = await critic_agent.validate_plan(state)
    return result


def route_after_critic(state: dict) -> str:
    validation = state.get("task_validation", {})
    iteration = state.get("iteration_count", 0)
    max_iter = state.get("max_iterations", 3)

    if validation and validation.get("valid", False):
        return "approved"

    if iteration >= max_iter:
        return "max_iterations"

    return "revise"


def build_planner_critic_subgraph():
    graph = StateGraph(PlannerCriticState)

    graph.add_node("planner", planner_node)
    graph.add_node("critic", critic_node)

    graph.add_edge(START, "planner")
    graph.add_edge("planner", "critic")

    graph.add_conditional_edges(
        "critic",
        route_after_critic,
        {
            "approved": END,
            "max_iterations": END,
            "revise": "planner",
        },
    )

    return graph.compile()
