from typing import Annotated, TypedDict
from langgraph.graph.message import add_messages


class PlanningState(TypedDict):
    project_id: str
    run_id: str
    messages: Annotated[list, add_messages]

    requirements_md: str | None
    requirements_json: dict | None

    selected_patterns: list[dict]
    pattern_rationale: str | None

    research_findings: list[dict]
    research_log: list[dict]

    architecture_md: str | None
    architecture_json: dict | None

    tasks: list[dict]
    task_validation: dict | None

    current_phase: str
    iteration_count: int
    max_iterations: int
    project_type: str | None
    feedback: str | None
    error: str | None
    approval_result: dict | None
