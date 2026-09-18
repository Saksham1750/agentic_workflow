import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import async_session_factory
from src.models.document import Document
from src.services.parsers.factory import get_parser
from src.services.embedding_service import embedding_service
from src.storage.file_store import file_store

logger = logging.getLogger(__name__)


async def parse_and_embed_document(project_id: str, document_id: str):
    logger.info(f"[INGEST] Starting parse_and_embed for doc={document_id} project={project_id}")
    try:
        async with async_session_factory() as db:
            result = await db.execute(
                select(Document).where(Document.id == document_id, Document.project_id == project_id)
            )
            doc = result.scalar_one_or_none()
            if not doc:
                logger.error(f"[INGEST] Document {document_id} not found for project {project_id}")
                return

            try:
                doc.status = "parsing"
                await db.commit()
                logger.info(f"[INGEST] Doc {document_id} status -> parsing")

                content = await file_store.read_file(doc.storage_path)
                logger.info(f"[INGEST] Doc {document_id} read {len(content)} bytes from {doc.storage_path}")

                parser = get_parser(doc.content_type)
                logger.info(f"[INGEST] Doc {document_id} parser={parser.__class__.__name__} for content_type={doc.content_type}")

                parsed = parser.parse(content)

                sections = parsed.get("sections", [])
                doc.sections_meta = {"sections": sections}
                doc.section_count = len(sections)
                logger.info(f"[INGEST] Doc {document_id} parsed {len(sections)} sections")

                chunk_count = await embedding_service.upsert_chunks(
                    project_id=project_id,
                    document_id=document_id,
                    sections=sections,
                )
                doc.chunk_count = chunk_count
                doc.status = "ready"

                await db.commit()
                logger.info(f"[INGEST] Doc {document_id} DONE: {len(sections)} sections, {chunk_count} chunks -> ready")

            except Exception as e:
                logger.exception(f"[INGEST] Doc {document_id} FAILED during pipeline")
                doc.status = "failed"
                doc.parse_error = str(e)
                await db.commit()
    except Exception as e:
        logger.exception(f"[INGEST] Doc {document_id} FAILED at outer scope")
