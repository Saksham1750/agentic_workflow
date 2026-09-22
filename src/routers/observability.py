import sqlite3
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse

from src.config import get_settings
from src.database import get_db, async_session_factory
from src.models.project import Project
from src.models.run import Run
from src.auth.dependencies import get_current_user
from src.exceptions import NotFoundError
from src.schemas.observability import (
    TraceSpanResponse,
    MetricRecordResponse,
    TokenSummaryResponse,
    TokenUsageResponse,
)
from src.services.report_service import report_service

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(tags=["observability"])
logger = logging.getLogger(__name__)


async def _get_project_or_404(project_id: str, user_id: str, db: AsyncSession) -> Project:
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.owner_id == user_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise NotFoundError("Project", project_id)
    return project


async def _get_run_or_404(project_id: str, run_id: str, db: AsyncSession) -> Run:
    result = await db.execute(
        select(Run).where(Run.id == run_id, Run.project_id == project_id)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise NotFoundError("Run", run_id)
    return run


@router.get("/projects/{project_id}/runs/{run_id}/traces", response_model=list[TraceSpanResponse])
async def get_run_traces(
    project_id: str,
    run_id: str,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_project_or_404(project_id, user_id, db)
    await _get_run_or_404(project_id, run_id, db)

    settings = get_settings()
    conn = sqlite3.connect(settings.SQLITE_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.execute(
            "SELECT * FROM trace_spans WHERE run_id = ? ORDER BY start_time",
            (run_id,),
        )
        rows = [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()

    return rows


@router.get("/projects/{project_id}/runs/{run_id}/metrics", response_model=list[MetricRecordResponse])
async def get_run_metrics(
    project_id: str,
    run_id: str,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_project_or_404(project_id, user_id, db)
    await _get_run_or_404(project_id, run_id, db)

    settings = get_settings()
    conn = sqlite3.connect(settings.SQLITE_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.execute(
            "SELECT * FROM metric_records WHERE run_id = ? ORDER BY timestamp",
            (run_id,),
        )
        rows = [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()

    return rows


@router.get("/projects/{project_id}/runs/{run_id}/tokens", response_model=TokenSummaryResponse)
async def get_run_tokens(
    project_id: str,
    run_id: str,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_project_or_404(project_id, user_id, db)
    await _get_run_or_404(project_id, run_id, db)

    settings = get_settings()
    conn = sqlite3.connect(settings.SQLITE_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.execute(
            "SELECT * FROM token_usage WHERE run_id = ? ORDER BY timestamp",
            (run_id,),
        )
        rows = [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()

    total_input = sum(r.get("input_tokens", 0) for r in rows)
    total_output = sum(r.get("output_tokens", 0) for r in rows)
    total_tokens = sum(r.get("total_tokens", 0) for r in rows)
    total_cost = sum(r.get("cost_usd", 0.0) for r in rows)

    return TokenSummaryResponse(
        usages=rows,
        total_input_tokens=total_input,
        total_output_tokens=total_output,
        total_tokens=total_tokens,
        total_cost_usd=total_cost,
    )


@router.get("/projects/{project_id}/runs/{run_id}/report")
async def get_run_report(
    project_id: str,
    run_id: str,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_project_or_404(project_id, user_id, db)
    await _get_run_or_404(project_id, run_id, db)

    settings = get_settings()
    from pathlib import Path

    report_path = (
        Path(settings.DATA_ROOT)
        / "projects"
        / project_id
        / "runs"
        / run_id
        / "report.md"
    )

    if not report_path.exists():
        try:
            report_md = await report_service.generate_report(run_id, project_id)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to generate report: {e}")
    else:
        report_md = report_path.read_text(encoding="utf-8")

    return PlainTextResponse(content=report_md, media_type="text/markdown")
