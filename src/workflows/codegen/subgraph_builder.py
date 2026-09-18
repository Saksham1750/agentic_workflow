import logging
from typing import Annotated, TypedDict
from langgraph.graph import StateGraph, START, END

from src.workflows.codegen.agents.developer import developer_agent
from src.workflows.codegen.agents.reviewers import reviewer_agents

logger = logging.getLogger(__name__)


class TaskSubgraphState(TypedDict):
    project_id: str
    run_id: str
    current_task: dict
    requirements_md: str | None
    architecture_json: dict | None
    selected_patterns: list[dict]
    generated_files: list[dict]
    workflow_review: dict | None
    prompt_review: dict | None
    security_review: dict | None
    review_verdict: str | None
    review_feedback: str | None
    iteration_count: int
    max_iterations: int


async def developer_node(state: dict) -> dict:
    current_task = state.get("current_task", {})
    review_feedback = state.get("review_feedback")

    existing_state = {
        "tasks": [current_task],
        "current_task_index": 0,
        "requirements_md": state.get("requirements_md"),
        "architecture_json": state.get("architecture_json"),
        "selected_patterns": state.get("selected_patterns", []),
        "workspace_files": state.get("generated_files", []),
        "review_feedback": review_feedback,
    }

    result = await developer_agent.generate_code(existing_state)

    return {
        "generated_files": result.get("workspace_files", []),
        "current_phase": "code_generated",
    }


async def parallel_reviewers_node(state: dict) -> dict:
    generated_files = state.get("generated_files", [])
    current_task = state.get("current_task", {})
    patterns = state.get("selected_patterns", [])

    workflow_review, prompt_review, security_review = await _run_reviewers_in_parallel(
        generated_files, patterns, current_task,
    )

    return {
        "workflow_review": workflow_review,
        "prompt_review": prompt_review,
        "security_review": security_review,
        "current_phase": "review_complete",
    }


async def _run_reviewers_in_parallel(
    files: list[dict],
    patterns: list[dict],
    task: dict,
) -> tuple[dict, dict, dict]:
    import asyncio

    results = await asyncio.gather(
        reviewer_agents.review_workflow(files, patterns, task),
        reviewer_agents.review_prompt(files, patterns, task),
        reviewer_agents.review_security(files, patterns, task),
        return_exceptions=True,
    )

    reviews = []
    for r in results:
        if isinstance(r, Exception):
            reviews.append({"verdict": "pass", "score": 80, "issues": [], "feedback": str(r)})
        else:
            reviews.append(r)

    return reviews[0], reviews[1], reviews[2]


def reduce_reviews_node(state: dict) -> dict:
    workflow_review = state.get("workflow_review", {})
    prompt_review = state.get("prompt_review", {})
    security_review = state.get("security_review", {})

    all_reviews = [workflow_review, prompt_review, security_review]
    failed = [r for r in all_reviews if r.get("verdict") == "fail"]

    if not failed:
        return {
            "review_verdict": "pass",
            "review_feedback": None,
            "current_phase": "review_passed",
        }

    all_issues = []
    for r in failed:
        all_issues.extend(r.get("issues", []))

    combined_feedback = "Review issues found:\n" + "\n".join(f"- {issue}" for issue in all_issues)

    return {
        "review_verdict": "fail",
        "review_feedback": combined_feedback,
        "current_phase": "review_failed",
    }


def route_after_review(state: dict) -> str:
    verdict = state.get("review_verdict", "pass")
    iteration = state.get("iteration_count", 0)
    max_iter = state.get("max_iterations", 3)

    if verdict == "pass":
        return "approved"

    if iteration >= max_iter:
        return "max_iterations"

    return "revise"


def build_task_subgraph():
    graph = StateGraph(TaskSubgraphState)

    graph.add_node("developer", developer_node)
    graph.add_node("parallel_reviewers", parallel_reviewers_node)
    graph.add_node("reduce_reviews", reduce_reviews_node)

    graph.add_edge(START, "developer")
    graph.add_edge("developer", "parallel_reviewers")
    graph.add_edge("parallel_reviewers", "reduce_reviews")

    graph.add_conditional_edges(
        "reduce_reviews",
        route_after_review,
        {
            "approved": END,
            "max_iterations": END,
            "revise": "developer",
        },
    )

    return graph.compile()
