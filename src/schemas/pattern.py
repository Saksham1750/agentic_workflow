from datetime import datetime
from pydantic import BaseModel, Field


class PatternCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    intent: str
    structure: str
    when_to_use: str
    strengths: str | None = None
    weaknesses: str | None = None
    example_use_case: str | None = None
    tags: list[str] | None = None


class PatternUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    intent: str | None = None
    structure: str | None = None
    when_to_use: str | None = None
    strengths: str | None = None
    weaknesses: str | None = None
    example_use_case: str | None = None
    tags: list[str] | None = None


class PatternResponse(BaseModel):
    id: str
    name: str
    intent: str
    structure: str
    when_to_use: str
    strengths: str | None
    weaknesses: str | None
    example_use_case: str | None
    tags: list[str] | None
    version: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PatternListResponse(BaseModel):
    patterns: list[PatternResponse]
    total: int


class PatternSearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    tags: list[str] | None = None
    n_results: int = Field(5, ge=1, le=50)


class PatternSearchResult(BaseModel):
    pattern: PatternResponse
    score: float


class PatternSearchResponse(BaseModel):
    results: list[PatternSearchResult]
    total: int
