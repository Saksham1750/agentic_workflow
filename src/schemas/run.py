from datetime import datetime
from pydantic import BaseModel, Field


class RunCreate(BaseModel):
    idempotency_key: str | None = None


class RunResponse(BaseModel):
    id: str
    project_id: str
    workflow_type: str
    status: str
    current_node: str | None
    config: dict | None
    error: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None

    model_config = {"from_attributes": True}


class RunListResponse(BaseModel):
    runs: list[RunResponse]
    total: int


class TaskCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=512)
    description: str | None = None
    acceptance_criteria: str | None = None
    pattern_refs: list[str] | None = None


class TaskUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=512)
    description: str | None = None
    acceptance_criteria: str | None = None
    pattern_refs: list[str] | None = None
    status: str | None = None
    task_index: int | None = None


class TaskResponse(BaseModel):
    id: str
    run_id: str
    project_id: str
    task_index: int
    title: str
    description: str | None
    acceptance_criteria: str | None
    pattern_refs: list[str] | None
    status: str
    output_files: dict | None
    created_at: datetime

    model_config = {"from_attributes": True}


class TaskListResponse(BaseModel):
    tasks: list[TaskResponse]
    total: int


class ClarificationRequest(BaseModel):
    request_id: str
    questions: list[dict]


class ClarificationResponse(BaseModel):
    request_id: str
    answers: list[dict]


class ApprovalRequest(BaseModel):
    run_id: str
    artifact_summary: str


class ApprovalResponse(BaseModel):
    approved: bool
    feedback: str | None = None
