from datetime import datetime
from pydantic import BaseModel


class TraceSpanResponse(BaseModel):
    id: str
    trace_id: str
    span_id: str
    parent_span_id: str | None
    name: str
    kind: str
    start_time: datetime
    end_time: datetime | None
    status_code: str
    status_message: str | None
    attributes: dict | None
    events: list | None
    project_id: str | None
    run_id: str | None

    model_config = {"from_attributes": True}


class MetricRecordResponse(BaseModel):
    id: str
    metric_name: str
    value: float
    unit: str
    attributes: dict | None
    timestamp: datetime
    project_id: str | None
    run_id: str | None

    model_config = {"from_attributes": True}


class TokenUsageResponse(BaseModel):
    id: str
    run_id: str
    project_id: str
    node_name: str
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_usd: float
    timestamp: datetime

    model_config = {"from_attributes": True}


class TokenSummaryResponse(BaseModel):
    usages: list[TokenUsageResponse]
    total_input_tokens: int
    total_output_tokens: int
    total_tokens: int
    total_cost_usd: float
