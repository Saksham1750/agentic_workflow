from datetime import datetime
from pydantic import BaseModel


class DocumentUploadResponse(BaseModel):
    id: str
    filename: str
    content_type: str
    status: str
    project_id: str


class DocumentStatusResponse(BaseModel):
    id: str
    filename: str
    content_type: str
    status: str
    section_count: int
    chunk_count: int
    parse_error: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class DocumentSectionsResponse(BaseModel):
    id: str
    filename: str
    sections: list[dict]


class SectionMeta(BaseModel):
    section_id: str
    title: str
    page: int | None = None
    kind: str = "other"
