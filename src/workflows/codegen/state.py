from typing import Annotated, TypedDict
from langgraph.graph.message import add_messages


class CodegenState(TypedDict):
    project_id: str
    run_id: str
    messages: Annotated[list, add_messages]

    requirements_md: str | None
    requirements_json: dict | None
    architecture_json: dict | None
    selected_patterns: list[dict]
    tasks: list[dict]
    current_task_index: int

    workspace_files: list[dict]
    review_results: list[dict]
    review_feedback: str | None

    current_phase: str
    iteration_count: int
    max_iterations: int
    error: str | None
    approval_result: dict | None
