from typing import Annotated, TypedDict, Optional
from langgraph.graph.message import add_messages


class RequirementsState(TypedDict):
    project_id: str
    run_id: str
    messages: Annotated[list, add_messages]
    documents: list[dict]
    requirements_md: str | None
    requirements_json: dict | None
    clarifications: list[dict]
    clarification_round: int
    max_clarification_rounds: int
    validation_result: dict | None
    current_phase: str
    error: str | None
    feedback: str | None
