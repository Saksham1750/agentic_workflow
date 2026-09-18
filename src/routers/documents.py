import uuid
import asyncio
from pathlib import Path

from fastapi import APIRouter, Depends, UploadFile, File, BackgroundTasks
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.models.project import Project
from src.models.document import Document
from src.schemas.document import DocumentUploadResponse, DocumentStatusResponse, DocumentSectionsResponse
from src.auth.dependencies import get_current_user
from src.config import get_settings
from src.exceptions import NotFoundError, UnsupportedMediaError, PayloadTooLargeError, ConflictError
from src.storage.file_store import file_store

router = APIRouter(prefix="/projects/{project_id}/documents", tags=["documents"])
settings = get_settings()

_background_tasks: set[asyncio.Task] = set()

MIME_TO_EXT = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "text/markdown": ".md",
    "text/plain": ".txt",
}


async def _get_project_or_404(project_id: str, user_id: str, db: AsyncSession) -> Project:
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.owner_id == user_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise NotFoundError("Project", project_id)
    return project


@router.post("", response_model=DocumentUploadResponse, status_code=201)
async def upload_document(
    background_tasks: BackgroundTasks,
    project_id: str,
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await _get_project_or_404(project_id, user_id, db)

    if file.content_type not in settings.ALLOWED_MIME_TYPES:
        raise UnsupportedMediaError(file.content_type or "unknown")

    content_type = file.content_type
    if content_type == "application/octet-stream":
        ext = Path(file.filename or "").suffix.lower()
        ext_map = {".pdf": "application/pdf", ".docx": MIME_TO_EXT.get("application/vnd.openxmlformats-officedocument.wordprocessingml.document"), ".md": "text/markdown", ".txt": "text/plain", ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation", ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
        resolved = ext_map.get(ext)
        if resolved:
            content_type = resolved
        else:
            raise UnsupportedMediaError(file.content_type or "unknown")

    content = await file.read()
    if len(content) > settings.max_upload_bytes:
        raise PayloadTooLargeError(settings.MAX_UPLOAD_SIZE_MB)

    import hashlib
    content_hash = hashlib.sha256(content).hexdigest()

    existing = await db.execute(
        select(Document).where(
            Document.project_id == project_id,
            Document.content_hash == content_hash,
        )
    )
    existing_doc = existing.scalar_one_or_none()
    if existing_doc:
        return DocumentUploadResponse(
            id=existing_doc.id,
            filename=existing_doc.filename,
            content_type=existing_doc.content_type,
            status=existing_doc.status,
            project_id=existing_doc.project_id,
        )

    document_id = str(uuid.uuid4())
    ext = MIME_TO_EXT.get(content_type, Path(file.filename or "").suffix or ".bin")
    filename = file.filename or f"document{ext}"

    storage_path, _ = await file_store.save_upload(
        project_id=project_id,
        document_id=document_id,
        filename=filename,
        content=content,
    )

    doc = Document(
        id=document_id,
        project_id=project_id,
        filename=filename,
        content_type=content_type,
        content_hash=content_hash,
        file_size=len(content),
        storage_path=storage_path,
        status="uploaded",
    )
    db.add(doc)
    await db.flush()
    await db.refresh(doc)
    await db.commit()

    from src.services.document_service import parse_and_embed_document
    task = asyncio.create_task(parse_and_embed_document(project_id, document_id))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    import logging
    logging.getLogger(__name__).info(f"[UPLOAD] Created background task for doc={document_id} project={project_id}, task={task}")

    return DocumentUploadResponse(
        id=doc.id,
        filename=doc.filename,
        content_type=doc.content_type,
        status=doc.status,
        project_id=doc.project_id,
    )


@router.get("/{document_id}", response_model=DocumentStatusResponse)
async def get_document_status(
    project_id: str,
    document_id: str,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_project_or_404(project_id, user_id, db)

    result = await db.execute(
        select(Document).where(Document.id == document_id, Document.project_id == project_id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise NotFoundError("Document", document_id)
    return doc


@router.get("/{document_id}/sections", response_model=DocumentSectionsResponse)
async def get_document_sections(
    project_id: str,
    document_id: str,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_project_or_404(project_id, user_id, db)

    result = await db.execute(
        select(Document).where(Document.id == document_id, Document.project_id == project_id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise NotFoundError("Document", document_id)

    return DocumentSectionsResponse(
        id=doc.id,
        filename=doc.filename,
        sections=doc.sections_meta.get("sections", []) if doc.sections_meta else [],
    )
