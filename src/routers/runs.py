import json
import logging
import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db, async_session_factory
from src.models.project import Project
from src.models.run import Run
from src.schemas.run import RunCreate, RunResponse, RunListResponse
from src.auth.dependencies import get_current_user
from src.exceptions import NotFoundError, ConflictError
from src.services.run_service import run_service
from src.services.sse_service import sse_service
from src.services.artifact_service import artifact_service
from src.services.lifecycle_service import initialize_checkpointer
from langgraph.types import Command

router = APIRouter(tags=["runs"])
logger = logging.getLogger(__name__)

_background_tasks: set[asyncio.Task] = set()


async def _get_project_or_404(project_id: str, user_id: str, db: AsyncSession) -> Project:
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.owner_id == user_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise NotFoundError("Project", project_id)
    return project


@router.post("/projects/{project_id}/workflows/{workflow_type}", response_model=RunResponse, status_code=202)
async def trigger_workflow(
    project_id: str,
    workflow_type: str,
    body: RunCreate | None = None,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if workflow_type not in ("requirements", "planning", "codegen"):
        raise HTTPException(status_code=400, detail="Invalid workflow type")

    await _get_project_or_404(project_id, user_id, db)

    idempotency_key = body.idempotency_key if body else None

    try:
        run = await run_service.create_run(
            project_id=project_id,
            workflow_type=workflow_type,
            user_id=user_id,
            idempotency_key=idempotency_key,
        )
    except ValueError as e:
        raise ConflictError(str(e))

    task = asyncio.create_task(_execute_workflow(run.id, project_id, workflow_type, run.thread_id))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return run


async def _execute_workflow(run_id: str, project_id: str, workflow_type: str, thread_id: str):
    try:
        await run_service.update_run_status(run_id, "running", current_node="starting")

        if workflow_type == "requirements":
            await _execute_requirements_workflow(run_id, project_id, thread_id)
        elif workflow_type == "planning":
            await _execute_planning_workflow(run_id, project_id, thread_id)
        elif workflow_type == "codegen":
            await _execute_codegen_workflow(run_id, project_id, thread_id)
        else:
            await run_service.update_run_status(
                run_id, "failed",
                error=f"Workflow '{workflow_type}' not yet implemented",
            )
    except Exception as e:
        logger.exception("Workflow %s failed for run %s", workflow_type, run_id)
        await run_service.update_run_status(run_id, "failed", error=str(e))


async def _execute_requirements_workflow(run_id: str, project_id: str, thread_id: str):
    from src.workflows.requirements.graph import build_requirements_graph
    from src.workflows.checkpointer import get_checkpointer

    checkpointer = await get_checkpointer()
    graph = await build_requirements_graph(checkpointer=checkpointer)

    config = {"configurable": {"thread_id": thread_id}}
    initial_state = {
        "project_id": project_id,
        "run_id": run_id,
        "messages": [],
        "documents": [],
        "requirements_md": None,
        "requirements_json": None,
        "clarifications": [],
        "clarification_round": 0,
        "max_clarification_rounds": 3,
        "validation_result": None,
        "current_phase": "starting",
        "error": None,
        "feedback": None,
    }

    await sse_service.emit_event(run_id=run_id, event_type="node_started", node_name="document_ingestion")

    result = await graph.ainvoke(initial_state, config)

    current_node = result.get("current_phase", "unknown")
    await run_service.update_run_status(run_id, "running", current_node=current_node)

    await sse_service.emit_event(run_id=run_id, event_type="node_completed", node_name="document_ingestion")

    if result.get("requirements_md") and result.get("requirements_json"):
        await artifact_service.save_requirements(
            project_id=project_id,
            run_id=run_id,
            requirements_md=result["requirements_md"],
            requirements_json=result["requirements_json"],
        )

    status = result.get("current_phase", "")
    if status == "approved":
        await run_service.update_run_status(run_id, "completed", current_node="approved")
    elif status in ("clarification_complete", "synthesized"):
        await run_service.update_run_status(run_id, "awaiting_human", current_node=current_node)
    elif status == "gap_analysis":
        pending = await _get_pending_hitl_payload(graph, config)
        await sse_service.emit_event(
            run_id=run_id,
            event_type="clarification_requested",
            node_name="clarification_generator",
            data=pending,
        )
        await run_service.update_run_status(run_id, "awaiting_human", current_node=current_node)
    else:
        await run_service.update_run_status(run_id, "completed", current_node=current_node)


async def _execute_planning_workflow(run_id: str, project_id: str, thread_id: str):
    from src.workflows.planning.graph import build_planning_graph
    from src.workflows.checkpointer import get_checkpointer

    checkpointer = await get_checkpointer()
    graph = await build_planning_graph(checkpointer=checkpointer)

    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 50}
    initial_state = {
        "project_id": project_id,
        "run_id": run_id,
        "messages": [],
        "requirements_md": None,
        "requirements_json": None,
        "selected_patterns": [],
        "pattern_rationale": None,
        "research_findings": [],
        "research_log": [],
        "architecture_md": None,
        "architecture_json": None,
        "tasks": [],
        "task_validation": None,
        "current_phase": "starting",
        "iteration_count": 0,
        "max_iterations": 3,
        "feedback": None,
        "error": None,
        "complexity": None,
        "approval_result": None,
    }

    nodes = [
        "load_requirements",
        "complexity_router",
        "pattern_selection",
        "research",
        "architecture",
        "planning",
        "validation",
        "approval",
    ]

    for node in nodes:
        await sse_service.emit_event(run_id=run_id, event_type="node_started", node_name=node)

    result = await graph.ainvoke(initial_state, config)

    for node in nodes:
        await sse_service.emit_event(run_id=run_id, event_type="node_completed", node_name=node)

    current_phase = result.get("current_phase", "unknown")

    pending = await _get_pending_hitl_payload(graph, config)
    if pending:
        await sse_service.emit_event(
            run_id=run_id,
            event_type="approval_requested",
            node_name="approval",
            data=pending,
        )
        await run_service.update_run_status(run_id, "awaiting_human", current_node="approval")
        return

    await run_service.update_run_status(run_id, "running", current_node=current_phase)

    if result.get("selected_patterns"):
        await artifact_service.save_pattern_report(
            project_id=project_id,
            run_id=run_id,
            patterns=result["selected_patterns"],
        )

    if all(result.get(k) for k in ["architecture_md", "architecture_json", "tasks"]):
        await artifact_service.save_planning_artifacts(
            project_id=project_id,
            run_id=run_id,
            selected_patterns=result.get("selected_patterns", []),
            research_findings=result.get("research_findings", []),
            architecture_md=result["architecture_md"],
            architecture_json=result["architecture_json"],
            tasks=result["tasks"],
            task_validation=result.get("task_validation", {}),
        )

    if current_phase == "approved":
        await run_service.update_run_status(run_id, "completed", current_node="approved")
    elif current_phase == "rejected":
        await run_service.update_run_status(run_id, "awaiting_human", current_node=current_phase)
    else:
        await run_service.update_run_status(run_id, "completed", current_node=current_phase)


async def _execute_codegen_workflow(run_id: str, project_id: str, thread_id: str):
    from src.workflows.codegen.graph import build_codegen_graph
    from src.workflows.checkpointer import get_checkpointer

    checkpointer = await get_checkpointer()
    graph = await build_codegen_graph(checkpointer=checkpointer)

    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 100}
    initial_state = {
        "project_id": project_id,
        "run_id": run_id,
        "messages": [],
        "requirements_md": None,
        "requirements_json": None,
        "architecture_json": None,
        "selected_patterns": [],
        "tasks": [],
        "current_task_index": 0,
        "workspace_files": [],
        "review_results": [],
        "review_feedback": None,
        "current_phase": "starting",
        "iteration_count": 0,
        "max_iterations": 3,
        "error": None,
        "approval_result": None,
    }

    nodes = [
        "load_artifacts",
        "execute_task",
        "process_next",
        "bundle_and_save",
        "approval",
    ]

    for node in nodes:
        await sse_service.emit_event(run_id=run_id, event_type="node_started", node_name=node)

    result = await graph.ainvoke(initial_state, config)

    for node in nodes:
        await sse_service.emit_event(run_id=run_id, event_type="node_completed", node_name=node)

    current_phase = result.get("current_phase", "unknown")

    pending = await _get_pending_hitl_payload(graph, config)
    if pending:
        await sse_service.emit_event(
            run_id=run_id,
            event_type="approval_requested",
            node_name="approval",
            data=pending,
        )
        await run_service.update_run_status(run_id, "awaiting_human", current_node="approval")
        return

    if current_phase == "approved":
        await run_service.update_run_status(run_id, "completed", current_node="approved")
    elif current_phase == "rejected":
        await run_service.update_run_status(run_id, "awaiting_human", current_node=current_phase)
    else:
        await run_service.update_run_status(run_id, "completed", current_node=current_phase)


async def _get_pending_hitl_payload(graph, config) -> dict | None:
    try:
        state_snapshot = await graph.aget_state(config)
        if state_snapshot and state_snapshot.tasks:
            for task in state_snapshot.tasks:
                if hasattr(task, "interrupts") and task.interrupts:
                    return task.interrupts[0].value if task.interrupts else None
    except Exception:
        pass
    return None


@router.get("/projects/{project_id}/runs", response_model=RunListResponse)
async def list_runs(
    project_id: str,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_project_or_404(project_id, user_id, db)
    result = await db.execute(select(Run).where(Run.project_id == project_id))
    runs = list(result.scalars().all())
    return RunListResponse(runs=runs, total=len(runs))


@router.get("/projects/{project_id}/runs/{run_id}", response_model=RunResponse)
async def get_run(
    project_id: str,
    run_id: str,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_project_or_404(project_id, user_id, db)
    result = await db.execute(select(Run).where(Run.id == run_id, Run.project_id == project_id))
    run = result.scalar_one_or_none()
    if not run:
        raise NotFoundError("Run", run_id)
    return run


@router.get("/projects/{project_id}/runs/{run_id}/pending-hitl")
async def get_pending_hitl(
    project_id: str,
    run_id: str,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_project_or_404(project_id, user_id, db)
    result = await db.execute(select(Run).where(Run.id == run_id, Run.project_id == project_id))
    run = result.scalar_one_or_none()
    if not run:
        raise NotFoundError("Run", run_id)

    if run.status != "awaiting_human":
        return {"pending": None, "status": run.status}

    import aiosqlite
    from src.config import get_settings
    settings = get_settings()

    try:
        conn = await aiosqlite.connect(settings.CHECKPOINT_DB_PATH)
        cursor = await conn.execute(
            "SELECT checkpoint FROM checkpoints WHERE thread_id = ? ORDER BY rowid DESC LIMIT 1",
            (run.thread_id,),
        )
        row = await cursor.fetchone()
        await conn.close()

        if not row:
            return {"pending": None, "status": run.status, "current_node": run.current_node}

        import msgpack
        checkpoint = msgpack.unpackb(row[0], raw=False)
        channel_values = checkpoint.get("channel_values", {})
        current_phase = channel_values.get("current_phase", "")

        payload = None
        if current_phase == "gap_analysis":
            clarifications = channel_values.get("clarifications", [])
            all_gaps = []
            for c in clarifications:
                all_gaps.extend(c.get("gaps", []))

            import uuid as _uuid
            questions = []
            for gap in all_gaps[:5]:
                questions.append({
                    "question_id": str(_uuid.uuid4()),
                    "question": f"Please clarify: {gap}",
                    "context": "This was identified during gap analysis of the uploaded documents.",
                })

            if not questions:
                questions.append({
                    "question_id": str(_uuid.uuid4()),
                    "question": "The gap analysis didn't identify any specific gaps. Can you provide additional requirements or confirm the current scope is sufficient?",
                    "context": "No gaps were automatically detected from the uploaded documents.",
                })

            payload = {
                "type": "clarification_request",
                "request_id": str(_uuid.uuid4()),
                "questions": questions,
                "round": channel_values.get("clarification_round", 0) + 1,
            }

        elif current_phase == "synthesized":
            payload = {
                "type": "approval_request",
                "run_id": run_id,
                "artifact_summary": "Requirements document ready for review",
            }

        return {"pending": payload, "status": run.status, "current_node": run.current_node}

    except Exception as e:
        return {"pending": None, "status": run.status, "current_node": run.current_node, "error": str(e)}


@router.get("/projects/{project_id}/runs/{run_id}/events")
async def get_run_events(
    project_id: str,
    run_id: str,
    last_event_id: int | None = Query(None),
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_project_or_404(project_id, user_id, db)

    result = await db.execute(select(Run).where(Run.id == run_id, Run.project_id == project_id))
    run = result.scalar_one_or_none()
    if not run:
        raise NotFoundError("Run", run_id)

    return StreamingResponse(
        sse_service.stream_events(run_id, last_event_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/projects/{project_id}/runs/{run_id}/resume", response_model=RunResponse)
async def resume_run(
    project_id: str,
    run_id: str,
    body: dict,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_project_or_404(project_id, user_id, db)

    result = await db.execute(select(Run).where(Run.id == run_id, Run.project_id == project_id))
    run = result.scalar_one_or_none()
    if not run:
        raise NotFoundError("Run", run_id)

    if run.status != "awaiting_human":
        raise ConflictError(f"Run is not awaiting human input (status: {run.status})")

    try:
        command_data = body.get("command", body)
        if isinstance(command_data, dict) and "resume" in command_data:
            command = Command(resume=command_data["resume"])
        else:
            command = Command(resume=command_data)

        await run_service.update_run_status(run_id, "running", current_node="resuming")

        task = asyncio.create_task(_resume_workflow(run_id, project_id, run.workflow_type, run.thread_id, command))
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)

        return run
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


async def _resume_workflow(run_id: str, project_id: str, workflow_type: str, thread_id: str, command):
    try:
        if workflow_type == "requirements":
            await _resume_requirements_workflow(run_id, project_id, thread_id, command)
        elif workflow_type == "planning":
            await _resume_planning_workflow(run_id, project_id, thread_id, command)
        elif workflow_type == "codegen":
            await _resume_codegen_workflow(run_id, project_id, thread_id, command)
    except Exception as e:
        logger.exception("Resume failed for run %s: %s", run_id, e)
        await run_service.update_run_status(run_id, "failed", error=str(e))


async def _resume_requirements_workflow(run_id: str, project_id: str, thread_id: str, command):
    from src.workflows.requirements.graph import build_requirements_graph
    from src.workflows.checkpointer import get_checkpointer

    checkpointer = await get_checkpointer()
    graph = await build_requirements_graph(checkpointer=checkpointer)

    config = {"configurable": {"thread_id": thread_id}}

    await sse_service.emit_event(run_id=run_id, event_type="node_started", node_name="resuming")

    result = await graph.ainvoke(command, config)

    current_node = result.get("current_phase", "unknown")

    if result.get("requirements_md") and result.get("requirements_json"):
        await artifact_service.save_requirements(
            project_id=project_id,
            run_id=run_id,
            requirements_md=result["requirements_md"],
            requirements_json=result["requirements_json"],
        )

    status = result.get("current_phase", "")
    if status == "approved":
        await run_service.update_run_status(run_id, "completed", current_node="approved")
    elif status == "synthesized":
        pending = await _get_pending_hitl_payload(graph, config)
        await sse_service.emit_event(
            run_id=run_id,
            event_type="approval_requested",
            node_name="validation",
            data=pending,
        )
        await run_service.update_run_status(run_id, "awaiting_human", current_node=current_node)
    elif status == "gap_analysis":
        pending = await _get_pending_hitl_payload(graph, config)
        await sse_service.emit_event(
            run_id=run_id,
            event_type="clarification_requested",
            node_name="clarification_generator",
            data=pending,
        )
        await run_service.update_run_status(run_id, "awaiting_human", current_node=current_node)
    elif status in ("clarification_complete", "validation_failed"):
        await run_service.update_run_status(run_id, "awaiting_human", current_node=current_node)
    else:
        await run_service.update_run_status(run_id, "completed", current_node=current_node)


async def _resume_planning_workflow(run_id: str, project_id: str, thread_id: str, command):
    from src.workflows.planning.graph import build_planning_graph
    from src.workflows.checkpointer import get_checkpointer

    checkpointer = await get_checkpointer()
    graph = await build_planning_graph(checkpointer=checkpointer)

    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 50}

    await sse_service.emit_event(run_id=run_id, event_type="node_started", node_name="resuming")

    result = await graph.ainvoke(command, config)

    current_phase = result.get("current_phase", "unknown")

    if all(result.get(k) for k in ["architecture_md", "architecture_json", "tasks"]):
        await artifact_service.save_planning_artifacts(
            project_id=project_id,
            run_id=run_id,
            selected_patterns=result.get("selected_patterns", []),
            research_findings=result.get("research_findings", []),
            architecture_md=result["architecture_md"],
            architecture_json=result["architecture_json"],
            tasks=result["tasks"],
            task_validation=result.get("task_validation", {}),
        )

    pending = await _get_pending_hitl_payload(graph, config)
    if pending:
        await sse_service.emit_event(
            run_id=run_id,
            event_type="approval_requested",
            node_name="approval",
            data=pending,
        )
        await run_service.update_run_status(run_id, "awaiting_human", current_node="approval")
        return

    status = result.get("current_phase", "")
    if status == "approved":
        await run_service.update_run_status(run_id, "completed", current_node="approved")
    elif status == "rejected":
        await run_service.update_run_status(run_id, "awaiting_human", current_node=current_phase)
    else:
        await run_service.update_run_status(run_id, "completed", current_node=current_phase)


async def _resume_codegen_workflow(run_id: str, project_id: str, thread_id: str, command):
    from src.workflows.codegen.graph import build_codegen_graph
    from src.workflows.checkpointer import get_checkpointer

    checkpointer = await get_checkpointer()
    graph = await build_codegen_graph(checkpointer=checkpointer)

    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 100}

    await sse_service.emit_event(run_id=run_id, event_type="node_started", node_name="resuming")

    result = await graph.ainvoke(command, config)

    current_phase = result.get("current_phase", "unknown")

    pending = await _get_pending_hitl_payload(graph, config)
    if pending:
        await sse_service.emit_event(
            run_id=run_id,
            event_type="approval_requested",
            node_name="approval",
            data=pending,
        )
        await run_service.update_run_status(run_id, "awaiting_human", current_node="approval")
        return

    status = result.get("current_phase", "")
    if status == "approved":
        await run_service.update_run_status(run_id, "completed", current_node="approved")
    elif status == "rejected":
        await run_service.update_run_status(run_id, "awaiting_human", current_node=current_phase)
    else:
        await run_service.update_run_status(run_id, "completed", current_node=current_phase)


@router.post("/projects/{project_id}/runs/{run_id}/clarifications")
async def submit_clarification(
    project_id: str,
    run_id: str,
    body: dict,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_project_or_404(project_id, user_id, db)

    result = await db.execute(select(Run).where(Run.id == run_id, Run.project_id == project_id))
    run = result.scalar_one_or_none()
    if not run:
        raise NotFoundError("Run", run_id)

    if run.status != "awaiting_human":
        raise ConflictError(f"Run is not awaiting human input (status: {run.status})")

    await run_service.update_run_status(run_id, "running", current_node="processing_clarifications")

    task = asyncio.create_task(_resume_workflow(
        run_id, project_id, run.workflow_type, run.thread_id,
        Command(resume=body.get("answers", body)),
    ))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return {"status": "accepted", "run_id": run_id}


@router.post("/projects/{project_id}/runs/{run_id}/approve")
async def approve_run(
    project_id: str,
    run_id: str,
    body: dict | None = None,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_project_or_404(project_id, user_id, db)

    result = await db.execute(select(Run).where(Run.id == run_id, Run.project_id == project_id))
    run = result.scalar_one_or_none()
    if not run:
        raise NotFoundError("Run", run_id)

    if run.status != "awaiting_human":
        raise ConflictError(f"Run is not awaiting human input (status: {run.status})")

    approval_data = {"approved": True}
    if body:
        approval_data.update(body)

    await run_service.update_run_status(run_id, "running", current_node="processing_approval")

    task = asyncio.create_task(_resume_workflow(
        run_id, project_id, run.workflow_type, run.thread_id,
        Command(resume=approval_data),
    ))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return {"status": "accepted", "run_id": run_id}


@router.post("/projects/{project_id}/runs/{run_id}/reject")
async def reject_run(
    project_id: str,
    run_id: str,
    body: dict,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_project_or_404(project_id, user_id, db)

    result = await db.execute(select(Run).where(Run.id == run_id, Run.project_id == project_id))
    run = result.scalar_one_or_none()
    if not run:
        raise NotFoundError("Run", run_id)

    if run.status != "awaiting_human":
        raise ConflictError(f"Run is not awaiting human input (status: {run.status})")

    rejection_data = {"approved": False, "feedback": body.get("feedback", "")}

    await run_service.update_run_status(run_id, "running", current_node="processing_rejection")

    task = asyncio.create_task(_resume_workflow(
        run_id, project_id, run.workflow_type, run.thread_id,
        Command(resume=rejection_data),
    ))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return {"status": "accepted", "run_id": run_id}


@router.get("/projects/{project_id}/runs/{run_id}/artifacts")
async def list_artifacts(
    project_id: str,
    run_id: str,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_project_or_404(project_id, user_id, db)
    result = await db.execute(select(Run).where(Run.id == run_id, Run.project_id == project_id))
    run = result.scalar_one_or_none()
    if not run:
        raise NotFoundError("Run", run_id)
    artifacts = await artifact_service.list_artifacts(project_id, run_id)
    return {"artifacts": artifacts, "run_id": run_id}


@router.get("/projects/{project_id}/runs/{run_id}/artifacts/{filename}")
async def get_artifact(
    project_id: str,
    run_id: str,
    filename: str,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_project_or_404(project_id, user_id, db)

    result = await db.execute(select(Run).where(Run.id == run_id, Run.project_id == project_id))
    run = result.scalar_one_or_none()
    if not run:
        raise NotFoundError("Run", run_id)

    from pathlib import Path
    from fastapi.responses import FileResponse
    from src.config import get_settings
    settings = get_settings()

    artifact_path = Path(settings.DATA_ROOT) / "projects" / project_id / "runs" / run_id / filename
    if not artifact_path.exists():
        raise NotFoundError("Artifact", filename)

    return FileResponse(
        path=str(artifact_path),
        filename=filename,
        media_type="application/octet-stream",
    )
