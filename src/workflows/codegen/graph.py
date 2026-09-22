import ast
import json
import logging
import re
from collections import Counter
from pathlib import Path
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt

from src.workflows.codegen.state import CodegenState
from src.workflows.codegen.agents.developer import developer_agent
from src.workflows.codegen.agents.reviewers import reviewer_agents
from src.workflows.codegen.subgraph_builder import build_task_subgraph
from src.observability.tracing import traced_node

logger = logging.getLogger(__name__)

IMPORT_TO_PACKAGE = {
    "fastapi": "fastapi",
    "uvicorn": "uvicorn[standard]",
    "sqlalchemy": "sqlalchemy[asyncio]",
    "aiosqlite": "aiosqlite",
    "pydantic": "pydantic",
    "pydantic_settings": "pydantic-settings",
    "langchain": "langchain",
    "langchain_core": "langchain-core",
    "langchain_openai": "langchain-openai",
    "langchain_groq": "langchain-groq",
    "langgraph": "langgraph",
    "chromadb": "chromadb",
    "httpx": "httpx",
    "aiofiles": "aiofiles",
    "jwt": "python-jose[cryptography]",
    "passlib": "passlib[bcrypt]",
    "multipart": "python-multipart",
    "yaml": "pyyaml",
    "markdown": "markdown",
    "pypdf": "pypdf",
    "docx": "python-docx",
    "pptx": "python-pptx",
    "openpyxl": "openpyxl",
    "numpy": "numpy",
    "pandas": "pandas",
    "requests": "requests",
    "aiohttp": "aiohttp",
    "jinja2": "jinja2",
    "alembic": "alembic",
    "psycopg2": "psycopg2-binary",
    "asyncpg": "asyncpg",
    "motor": "motor",
    "pymongo": "pymongo",
    "celery": "celery",
    "redis": "redis",
}


@traced_node("load_artifacts")
async def load_planning_artifacts_node(state: dict) -> dict:
    import asyncio
    from src.services.artifact_service import artifact_service
    from src.database import async_session_factory
    from src.models.run import Run
    from src.services.run_service import run_service
    from sqlalchemy import select

    run_id = state.get("run_id", "")
    project_id = state.get("project_id", "")

    try:
        await run_service.update_run_status(run_id, "running", current_node="load_artifacts")
    except Exception:
        pass

    logger.info("[CODEGEN] load_planning_artifacts_node START for project %s", project_id)

    try:
        async with asyncio.timeout(10):
            async with async_session_factory() as db:
                result = await db.execute(
                    select(Run).where(
                        Run.project_id == project_id,
                        Run.workflow_type == "planning",
                        Run.status == "completed",
                    ).order_by(Run.created_at.desc()).limit(1)
                )
                planning_run = result.scalar_one_or_none()
    except asyncio.TimeoutError:
        logger.error("[CODEGEN] load_planning_artifacts_node DB query TIMED OUT for project %s", project_id)
        return {
            "requirements_md": None,
            "requirements_json": None,
            "architecture_json": None,
            "selected_patterns": [],
            "tasks": [],
            "current_task_index": 0,
            "current_phase": "load_error",
            "error": "Timeout loading planning artifacts from database",
        }

    logger.info("[CODEGEN] load_planning_artifacts_node DB query done, planning_run=%s", planning_run.id if planning_run else None)

    if not planning_run:
        logger.warning("[CODEGEN] No completed planning run found for project %s", project_id)
        return {
            "requirements_md": None,
            "requirements_json": None,
            "architecture_json": None,
            "selected_patterns": [],
            "tasks": [],
            "current_task_index": 0,
            "current_phase": "no_planning_artifacts",
        }

    logger.info("[CODEGEN] Loading planning state from run %s", planning_run.id)
    planning_state = await artifact_service.load_planning_state(
        project_id=project_id,
        run_id=planning_run.id,
    )

    task_count = len(planning_state.get("tasks", []))
    pattern_count = len(planning_state.get("selected_patterns", []))
    logger.info(
        "[CODEGEN] Loaded planning artifacts from run %s: %d patterns, %d tasks, has_requirements_md=%s, has_arch=%s",
        planning_run.id,
        pattern_count,
        task_count,
        "yes" if planning_state.get("requirements_md") else "no",
        "yes" if planning_state.get("architecture_json") else "no",
    )

    return {
        "requirements_md": planning_state.get("requirements_md"),
        "requirements_json": planning_state.get("requirements_json"),
        "architecture_json": planning_state.get("architecture_json"),
        "selected_patterns": planning_state.get("selected_patterns", []),
        "tasks": planning_state.get("tasks", []),
        "current_task_index": 0,
        "current_phase": "artifacts_loaded",
    }


@traced_node("execute_task")
async def execute_task_node(state: dict) -> dict:
    from src.services.run_service import run_service

    run_id = state.get("run_id", "")
    try:
        await run_service.update_run_status(run_id, "running", current_node="execute_task")
    except Exception:
        pass

    tasks = state.get("tasks", [])
    current_index = state.get("current_task_index", 0)

    if current_index >= len(tasks):
        return {"current_phase": "all_tasks_completed"}

    current_task = tasks[current_index]
    logger.info("Executing task %d/%d: %s", current_index + 1, len(tasks), current_task.get("title", "unknown"))

    task_subgraph = build_task_subgraph()

    subgraph_result = await task_subgraph.ainvoke({
        "project_id": state.get("project_id", ""),
        "run_id": state.get("run_id", ""),
        "current_task": current_task,
        "requirements_md": state.get("requirements_md"),
        "architecture_json": state.get("architecture_json"),
        "selected_patterns": state.get("selected_patterns", []),
        "workspace_files": state.get("workspace_files", []),
        "generated_files": [],
        "workflow_review": None,
        "prompt_review": None,
        "security_review": None,
        "review_verdict": None,
        "review_feedback": None,
        "iteration_count": 0,
        "max_iterations": state.get("max_iterations", 3),
    })

    new_files = subgraph_result.get("generated_files", [])
    existing_files = state.get("workspace_files", [])
    updated_files = existing_files + new_files

    logger.info(
        "Task %s generated %d files (total: %d). Review verdict: %s",
        current_task.get("task_id", "?"),
        len(new_files),
        len(updated_files),
        subgraph_result.get("review_verdict", "n/a"),
    )

    return {
        "workspace_files": updated_files,
        "current_task_index": current_index + 1,
        "current_phase": "task_completed",
    }


@traced_node("process_next")
async def process_next_task_node(state: dict) -> dict:
    from src.services.run_service import run_service

    run_id = state.get("run_id", "")
    try:
        await run_service.update_run_status(run_id, "running", current_node="process_next")
    except Exception:
        pass

    current_index = state.get("current_task_index", 0)
    tasks = state.get("tasks", [])

    if current_index >= len(tasks):
        return {"current_phase": "all_tasks_completed"}

    return {"current_phase": "processing_next_task"}


def route_task_iteration(state: dict) -> str:
    current_index = state.get("current_task_index", 0)
    tasks = state.get("tasks", [])

    if current_index >= len(tasks):
        return "completed"

    return "next_task"


def _extract_imports_from_files(files: list[dict]) -> set[str]:
    third_party = set()
    for f in files:
        content = f.get("content", "")
        if not f.get("path", "").endswith(".py"):
            continue
        try:
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        pkg = alias.name.split(".")[0]
                        if pkg in IMPORT_TO_PACKAGE:
                            third_party.add(IMPORT_TO_PACKAGE[pkg])
                elif isinstance(node, ast.ImportFrom) and node.module:
                    pkg = node.module.split(".")[0]
                    if pkg in IMPORT_TO_PACKAGE:
                        third_party.add(IMPORT_TO_PACKAGE[pkg])
        except SyntaxError:
            pass
    return third_party


def _detect_framework(files: list[dict]) -> str | None:
    content_all = " ".join(f.get("content", "") for f in files)
    if "FastAPI" in content_all or "fastapi" in content_all:
        return "fastapi"
    if "Flask" in content_all:
        return "flask"
    if "Django" in content_all:
        return "django"
    return None


def _generate_requirements_txt(files: list[dict]) -> str:
    packages = _extract_imports_from_files(files)
    framework = _detect_framework(files)

    lines = [
        "# Auto-generated requirements.txt",
        "# Install with: pip install -r requirements.txt",
        "",
    ]

    if framework == "fastapi":
        lines.extend([
            "fastapi>=0.104.0",
            "uvicorn[standard]>=0.24.0",
            "pydantic>=2.5.0",
            "pydantic-settings>=2.1.0",
            "python-multipart>=0.0.6",
            "",
        ])

    standard_libs = {"os", "sys", "json", "logging", "typing", "pathlib", "asyncio",
                     "datetime", "collections", "abc", "re", "ast", "io", "zipfile",
                     "hashlib", "hmac", "secrets", "base64", "functools", "dataclasses",
                     "enum", "time", "uuid", "copy", "math", "random", "string",
                     "textwrap", "contextlib", "contextvars", "traceback", "inspect"}

    sorted_pkgs = sorted(packages)
    for pkg in sorted_pkgs:
        if pkg not in standard_libs:
            lines.append(pkg)

    lines.extend(["", "# Optional: uncomment if needed", "# python-dotenv>=1.0.0"])

    return "\n".join(lines) + "\n"


def _generate_init_files(files: list[dict]) -> list[dict]:
    dirs = set()
    for f in files:
        path = f.get("path", "")
        parts = Path(path).parts
        for i in range(1, len(parts)):
            if parts[i].endswith(".py") and parts[i] != "__init__.py":
                dir_path = "/".join(parts[:i])
                dirs.add(dir_path)

    init_files = []
    for d in sorted(dirs):
        init_files.append({
            "path": f"{d}/__init__.py",
            "content": f'"""Package: {d.split("/")[-1]}"""\n',
            "action": "create",
        })

    return init_files


def _generate_main_py(files: list[dict], tasks: list[dict]) -> str:
    framework = _detect_framework(files)

    if framework == "fastapi":
        return _generate_fastapi_main(files, tasks)

    return _generate_generic_main(files, tasks)


def _generate_fastapi_main(files: list[dict], tasks: list[dict]) -> str:
    imports = []
    routers = []
    seen = set()

    for f in files:
        content = f.get("content", "")
        path = f.get("path", "")
        if not path.endswith(".py"):
            continue

        module = path.replace("/", ".").replace("\\", ".").replace(".py", "")

        try:
            tree = ast.parse(content)
            for node in ast.iter_child_nodes(tree):
                if isinstance(node, ast.ClassDef):
                    class_name = node.name
                    if module not in seen:
                        imports.append(f"from {module} import {class_name}")
                        seen.add(module)
                elif isinstance(node, ast.AsyncFunctionDef) or isinstance(node, ast.FunctionDef):
                    if node.name.startswith("router"):
                        if module not in seen:
                            imports.append(f"from {module} import router")
                            routers.append(class_name if False else "router")
                            seen.add(module)
        except SyntaxError:
            pass

    return f'''"""
Main entry point for the generated application.

Run with:
    uvicorn main:app --reload --host 0.0.0.0 --port 8000

Or:
    python main.py
"""

import logging
import sys
from contextlib import asynccontextmanager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

try:
    from fastapi import FastAPI
except ImportError:
    logger.error("FastAPI not installed. Run: pip install fastapi uvicorn[standard]")
    sys.exit(1)

{chr(10).join(imports) if imports else "# Import your modules here"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting application...")
    yield
    logger.info("Shutting down application...")


app = FastAPI(
    title="Generated Application",
    description="Generated by AI Agent Factory",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/")
async def root():
    return {{"message": "Application is running", "status": "healthy"}}


@app.get("/health")
async def health():
    return {{"status": "ok"}}


{"".join(f'app.include_router({r})\\n' for r in routers if routers) if routers else ""}

if __name__ == "__main__":
    try:
        import uvicorn
        uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
    except ImportError:
        logger.error("uvicorn not installed. Run: pip install uvicorn[standard]")
        sys.exit(1)
'''


def _generate_generic_main(files: list[dict], tasks: list[dict]) -> str:
    imports = []
    seen = set()

    for f in files:
        path = f.get("path", "")
        if not path.endswith(".py") or path.endswith("__init__.py"):
            continue
        module = path.replace("/", ".").replace("\\", ".").replace(".py", "")
        if module not in seen:
            imports.append(f"import {module}")
            seen.add(module)

    return f'''"""
Main entry point for the generated application.

Run with: python main.py
"""

import asyncio
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

{chr(10).join(imports) if imports else "# Import your modules here"}


async def main():
    logger.info("Application starting...")
    # Add your application logic here
    logger.info("Application finished.")


if __name__ == "__main__":
    asyncio.run(main())
'''


@traced_node("generate_scaffolding")
async def generate_scaffolding_node(state: dict) -> dict:
    from src.services.run_service import run_service
    run_id = state.get("run_id", "")
    try:
        await run_service.update_run_status(run_id, "running", current_node="generate_scaffolding")
    except Exception:
        pass

    workspace_files = state.get("workspace_files", [])

    requirements_txt = _generate_requirements_txt(workspace_files)
    main_py = _generate_main_py(workspace_files, state.get("tasks", []))
    init_files = _generate_init_files(workspace_files)

    scaffolding = [{"path": "requirements.txt", "content": requirements_txt, "action": "create", "task_id": "scaffolding"}]
    scaffolding.append({"path": "main.py", "content": main_py, "action": "create", "task_id": "scaffolding"})
    scaffolding.extend(init_files)

    updated = workspace_files + scaffolding

    logger.info("Generated scaffolding: requirements.txt, main.py, %d __init__.py files", len(init_files))

    return {
        "workspace_files": updated,
        "current_phase": "scaffolding_generated",
    }


@traced_node("bundle_and_save")
async def bundle_and_save_node(state: dict) -> dict:
    from src.workflows.codegen.services.workspace_service import workspace_service
    from src.services.artifact_service import artifact_service
    from src.services.run_service import run_service

    run_id = state.get("run_id", "")
    try:
        await run_service.update_run_status(run_id, "running", current_node="bundle_and_save")
    except Exception:
        pass

    project_id = state.get("project_id", "")
    run_id = state.get("run_id", "")
    workspace_files = state.get("workspace_files", [])

    logger.info("Bundle: writing %d files to workspace", len(workspace_files))

    files_written = await workspace_service.write_files(
        project_id=project_id,
        run_id=run_id,
        files=[{"path": f["path"], "content": f["content"], "action": f.get("action", "create")} for f in workspace_files],
    )

    logger.info("Bundle: %d files written to disk", len(files_written))

    task_file_map = {}
    for f in workspace_files:
        task_id = f.get("task_id", "unknown")
        if task_id not in task_file_map:
            task_file_map[task_id] = []
        task_file_map[task_id].append(f["path"])

    bundle_path = await workspace_service.create_bundle(
        project_id=project_id,
        run_id=run_id,
        task_file_map=task_file_map,
        tasks=state.get("tasks", []),
        architecture_json=state.get("architecture_json"),
        selected_patterns=state.get("selected_patterns", []),
    )

    logger.info("Bundle created at %s", bundle_path)

    return {
        "current_phase": "bundled",
    }


@traced_node("approval")
async def approval_node(state: dict) -> dict:
    from src.services.run_service import run_service
    run_id = state.get("run_id", "")
    try:
        await run_service.update_run_status(run_id, "running", current_node="approval")
    except Exception:
        pass

    workspace_files = state.get("workspace_files", [])
    tasks = state.get("tasks", [])

    approval = interrupt({
        "type": "approval_request",
        "run_id": state.get("run_id"),
        "file_count": len(workspace_files),
        "task_count": len(tasks),
        "files_summary": [{"path": f["path"], "task_id": f.get("task_id")} for f in workspace_files[:50]],
    })

    if isinstance(approval, dict) and approval.get("approved"):
        return {
            "approval_result": {"approved": True},
            "current_phase": "approved",
        }
    else:
        feedback = approval.get("feedback", "No feedback provided") if isinstance(approval, dict) else str(approval)
        return {
            "approval_result": {"approved": False, "feedback": feedback},
            "current_phase": "rejected",
        }


def route_after_approval(state: dict) -> str:
    phase = state.get("current_phase", "")
    if phase == "rejected":
        return "execute_task"
    return END


async def build_codegen_graph(checkpointer=None):
    graph = StateGraph(CodegenState)

    graph.add_node("load_artifacts", load_planning_artifacts_node)
    graph.add_node("execute_task", execute_task_node)
    graph.add_node("process_next", process_next_task_node)
    graph.add_node("generate_scaffolding", generate_scaffolding_node)
    graph.add_node("bundle_and_save", bundle_and_save_node)
    graph.add_node("approval", approval_node)

    graph.add_edge(START, "load_artifacts")
    graph.add_edge("load_artifacts", "execute_task")

    graph.add_conditional_edges(
        "execute_task",
        route_task_iteration,
        {
            "next_task": "process_next",
            "completed": "generate_scaffolding",
        },
    )

    graph.add_edge("process_next", "execute_task")
    graph.add_edge("generate_scaffolding", "bundle_and_save")
    graph.add_edge("bundle_and_save", "approval")

    graph.add_conditional_edges(
        "approval",
        route_after_approval,
        {
            "execute_task": "execute_task",
            END: END,
        },
    )

    compiled = graph.compile(
        checkpointer=checkpointer,
    )

    return compiled
