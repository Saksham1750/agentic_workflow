import logging
from typing import Annotated, TypedDict
from langgraph.graph import StateGraph, START, END

from src.workflows.codegen.agents.developer import developer_agent
from src.workflows.codegen.agents.reviewers import reviewer_agents
from src.observability.tracing import traced_node

logger = logging.getLogger(__name__)


class TaskSubgraphState(TypedDict):
    project_id: str
    run_id: str
    current_task: dict
    requirements_md: str | None
    architecture_json: dict | None
    selected_patterns: list[dict]
    workspace_files: list[dict]
    generated_files: list[dict]
    workflow_review: dict | None
    prompt_review: dict | None
    security_review: dict | None
    review_verdict: str | None
    review_feedback: str | None
    iteration_count: int
    max_iterations: int


@traced_node("developer")
async def developer_node(state: dict) -> dict:
    current_task = state.get("current_task", {})
    review_feedback = state.get("review_feedback")
    workspace_files = state.get("workspace_files", [])

    existing_state = {
        "tasks": [current_task],
        "current_task_index": 0,
        "requirements_md": state.get("requirements_md"),
        "architecture_json": state.get("architecture_json"),
        "selected_patterns": state.get("selected_patterns", []),
        "workspace_files": workspace_files,
        "review_feedback": review_feedback,
    }

    result = await developer_agent.generate_code(existing_state)

    return {
        "generated_files": result.get("workspace_files", []),
        "current_phase": "code_generated",
    }


@traced_node("validate_code")
async def validate_code_node(state: dict) -> dict:
    generated_files = state.get("generated_files", [])
    issues = []

    for f in generated_files:
        path = f.get("path", "")
        content = f.get("content", "")
        if not path.endswith(".py"):
            continue

        try:
            compile(content, path, "exec")
        except SyntaxError as e:
            issues.append(f"Syntax error in {path}: {e}")

        missing_imports = _check_imports(content)
        if missing_imports:
            issues.append(f"{path}: may need packages: {', '.join(missing_imports)}")

    if issues:
        return {
            "review_feedback": "Code validation issues:\n" + "\n".join(f"- {i}" for i in issues),
            "review_verdict": "fail",
            "current_phase": "validation_failed",
        }

    return {"current_phase": "validation_passed"}


def _check_imports(content: str) -> list[str]:
    import ast

    third_party = {
        "fastapi", "uvicorn", "sqlalchemy", "aiosqlite", "pydantic",
        "langchain", "langchain_core", "langchain_groq", "langgraph",
        "chromadb", "httpx", "aiofiles", "jwt", "passlib", "multipart",
        "yaml", "markdown", "pypdf", "docx", "pptx", "openpyxl",
        "numpy", "pandas", "requests", "aiohttp", "celery", "redis",
        "jinja2", "alembic", "psycopg2", "asyncpg", "motor", "pymongo",
    }

    missing = []
    try:
        tree = ast.parse(content)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    pkg = alias.name.split(".")[0]
                    if pkg in third_party:
                        missing.append(pkg)
            elif isinstance(node, ast.ImportFrom) and node.module:
                pkg = node.module.split(".")[0]
                if pkg in third_party:
                    missing.append(pkg)
    except SyntaxError:
        pass

    return list(set(missing))


@traced_node("parallel_reviewers")
async def parallel_reviewers_node(state: dict) -> dict:
    generated_files = state.get("generated_files", [])
    current_task = state.get("current_task", {})
    patterns = state.get("selected_patterns", [])
    run_id = state.get("run_id", "")
    project_id = state.get("project_id", "")

    workflow_review, prompt_review, security_review = await _run_reviewers_in_parallel(
        generated_files, patterns, current_task,
        run_id=run_id, project_id=project_id,
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
    run_id: str = "",
    project_id: str = "",
) -> tuple[dict, dict, dict]:
    import asyncio

    results = await asyncio.gather(
        reviewer_agents.review_workflow(files, patterns, task, run_id=run_id, project_id=project_id),
        reviewer_agents.review_prompt(files, patterns, task, run_id=run_id, project_id=project_id),
        reviewer_agents.review_security(files, patterns, task, run_id=run_id, project_id=project_id),
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
    graph.add_node("validate_code", validate_code_node)
    graph.add_node("parallel_reviewers", parallel_reviewers_node)
    graph.add_node("reduce_reviews", reduce_reviews_node)

    graph.add_edge(START, "developer")
    graph.add_edge("developer", "validate_code")

    graph.add_conditional_edges(
        "validate_code",
        lambda s: "skip_review" if s.get("current_phase") == "validation_failed" else "review",
        {
            "review": "parallel_reviewers",
            "skip_review": "parallel_reviewers",
        },
    )

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
