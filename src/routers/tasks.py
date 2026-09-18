from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.models.project import Project
from src.models.task import Task
from src.schemas.run import TaskCreate, TaskUpdate, TaskResponse, TaskListResponse
from src.auth.dependencies import get_current_user
from src.exceptions import NotFoundError

router = APIRouter(prefix="/projects/{project_id}/tasks", tags=["tasks"])


async def _get_project_or_404(project_id: str, user_id: str, db: AsyncSession) -> Project:
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.owner_id == user_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise NotFoundError("Project", project_id)
    return project


@router.get("", response_model=TaskListResponse)
async def list_tasks(
    project_id: str,
    run_id: str | None = None,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_project_or_404(project_id, user_id, db)

    query = select(Task).where(Task.project_id == project_id)
    if run_id:
        query = query.where(Task.run_id == run_id)
    query = query.order_by(Task.task_index)

    result = await db.execute(query)
    tasks = list(result.scalars().all())
    return TaskListResponse(tasks=tasks, total=len(tasks))


@router.post("", response_model=TaskResponse, status_code=201)
async def create_task(
    project_id: str,
    body: TaskCreate,
    run_id: str = None,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_project_or_404(project_id, user_id, db)

    if not run_id:
        from src.exceptions import AppError
        raise AppError(code="missing_run_id", message="run_id query parameter required", status_code=422)

    result = await db.execute(
        select(Task).where(Task.project_id == project_id, Task.run_id == run_id)
    )
    existing = list(result.scalars().all())
    next_index = max((t.task_index for t in existing), default=-1) + 1

    task = Task(
        run_id=run_id,
        project_id=project_id,
        task_index=next_index,
        title=body.title,
        description=body.description,
        acceptance_criteria=body.acceptance_criteria,
        pattern_refs=body.pattern_refs,
    )
    db.add(task)
    await db.flush()
    await db.refresh(task)
    return task


@router.patch("/{task_id}", response_model=TaskResponse)
async def update_task(
    project_id: str,
    task_id: str,
    body: TaskUpdate,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_project_or_404(project_id, user_id, db)

    result = await db.execute(
        select(Task).where(Task.id == task_id, Task.project_id == project_id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise NotFoundError("Task", task_id)

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(task, field, value)

    await db.flush()
    await db.refresh(task)
    return task
