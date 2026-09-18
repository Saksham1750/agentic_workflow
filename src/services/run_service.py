import uuid
import logging
import asyncio
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import async_session_factory
from src.models.run import Run
from src.services.sse_service import sse_service
from src.services.artifact_service import artifact_service
from src.services.lifecycle_service import initialize_checkpointer

logger = logging.getLogger(__name__)

_project_locks: dict[str, asyncio.Lock] = {}


def _get_project_lock(project_id: str) -> asyncio.Lock:
    if project_id not in _project_locks:
        _project_locks[project_id] = asyncio.Lock()
    return _project_locks[project_id]


class RunService:
    async def create_run(
        self,
        project_id: str,
        workflow_type: str,
        user_id: str,
        idempotency_key: str | None = None,
    ) -> Run:
        async with async_session_factory() as db:
            if idempotency_key:
                result = await db.execute(
                    select(Run).where(
                        Run.idempotency_key == idempotency_key,
                        Run.project_id == project_id,
                    )
                )
                existing = result.scalar_one_or_none()
                if existing:
                    return existing

            lock = _get_project_lock(project_id)
            if lock.locked():
                raise ValueError(f"An active run already exists for project {project_id}")

            async with lock:
                result = await db.execute(
                    select(Run).where(
                        Run.project_id == project_id,
                        Run.status.in_(["pending", "running", "awaiting_human"]),
                    )
                )
                active = result.scalar_one_or_none()
                if active:
                    raise ValueError(f"An active run already exists for project {project_id}")

                thread_id = str(uuid.uuid4())
                run = Run(
                    id=str(uuid.uuid4()),
                    project_id=project_id,
                    workflow_type=workflow_type,
                    status="pending",
                    idempotency_key=idempotency_key,
                    thread_id=thread_id,
                )
                db.add(run)
                await db.commit()
                await db.refresh(run)

                await sse_service.emit_event(
                    run_id=run.id,
                    event_type="run_created",
                    data={"project_id": project_id, "workflow_type": workflow_type},
                )

                return run

    async def update_run_status(
        self,
        run_id: str,
        status: str,
        current_node: str | None = None,
        error: str | None = None,
    ):
        async with async_session_factory() as db:
            result = await db.execute(select(Run).where(Run.id == run_id))
            run = result.scalar_one_or_none()
            if not run:
                return

            run.status = status
            if current_node is not None:
                run.current_node = current_node
            if error is not None:
                run.error = error
            if status in ("completed", "failed", "cancelled"):
                run.completed_at = datetime.now(timezone.utc)

            await db.commit()

            await sse_service.emit_event(
                run_id=run_id,
                event_type=f"run_{status}",
                node_name=current_node,
                data={"status": status, "error": error},
            )

    async def resume_run(self, run_id: str, command) -> dict:
        async with async_session_factory() as db:
            result = await db.execute(select(Run).where(Run.id == run_id))
            run = result.scalar_one_or_none()
            if not run:
                raise ValueError(f"Run {run_id} not found")
            if run.status != "awaiting_human":
                raise ValueError(f"Run {run_id} is not awaiting human input (status: {run.status})")

        return {"run_id": run_id, "command": command}


run_service = RunService()
