from pydantic import BaseModel, Field


class HITLMessage(BaseModel):
    type: str = Field(..., pattern="^(clarification_request|clarification_response|approval_request|approval_response|status_update|error)$")
    request_id: str | None = None
    payload: dict | None = None


class HITLClarificationQuestion(BaseModel):
    question_id: str
    question: str
    context: str | None = None
    options: list[str] | None = None


class HITLApprovalDecision(BaseModel):
    approved: bool
    feedback: str | None = None
