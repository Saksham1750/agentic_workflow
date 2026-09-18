import json
import logging
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt

from src.workflows.codegen.state import CodegenState
from src.workflows.codegen.agents.developer import developer_agent
from src.workflows.codegen.agents.reviewers import reviewer_agents
from src.workflows.codegen.subgraph_builder import build_task_subgraph

logger = logging.getLogger(__name__)


async def load_planning_artifacts_node(state: dict) -> dict:
    from src.services.artifact_service import artifact_service

    project_id = state.get("project_id", "")
    run_id = state.get("run_id", "")

    planning_state = await artifact_service.load_planning_state(project_id, run_id)

    return {
        "requirements_md": planning_state.get("requirements_md"),
        "requirements_json": planning_state.get("requirements_json"),
        "architecture_json": planning_state.get("architecture_json"),
        "selected_patterns": planning_state.get("selected_patterns", []),
        "tasks": planning_state.get("tasks", []),
        "current_task_index": 0,
        "current_phase": "artifacts_loaded",
    }


async def execute_task_node(state: dict) -> dict:
    tasks = state.get("tasks", [])
    current_index = state.get("current_task_index", 0)

    if current_index >= len(tasks):
        return {"current_phase": "all_tasks_completed"}

    current_task = tasks[current_index]

    task_subgraph = build_task_subgraph()

    subgraph_result = await task_subgraph.ainvoke({
        "project_id": state.get("project_id", ""),
        "run_id": state.get("run_id", ""),
        "current_task": current_task,
        "requirements_md": state.get("requirements_md"),
        "architecture_json": state.get("architecture_json"),
        "selected_patterns": state.get("selected_patterns", []),
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

    return {
        "workspace_files": updated_files,
        "current_task_index": current_index + 1,
        "current_phase": "task_completed",
    }


async def process_next_task_node(state: dict) -> dict:
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


async def bundle_and_save_node(state: dict) -> dict:
    from src.workflows.codegen.services.workspace_service import workspace_service
    from src.services.artifact_service import artifact_service

    project_id = state.get("project_id", "")
    run_id = state.get("run_id", "")
    workspace_files = state.get("workspace_files", [])

    files_written = await workspace_service.write_files(
        project_id=project_id,
        run_id=run_id,
        files=[{"path": f["path"], "content": f["content"], "action": f.get("action", "create")} for f in workspace_files],
    )

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
    )

    return {
        "current_phase": "bundled",
    }


async def approval_node(state: dict) -> dict:
    workspace_files = state.get("workspace_files", [])
    tasks = state.get("tasks", [])

    approval = interrupt({
        "type": "approval_request",
        "run_id": state.get("run_id"),
        "file_count": len(workspace_files),
        "task_count": len(tasks),
        "files_summary": [{"path": f["path"], "task_id": f.get("task_id")} for f in workspace_files[:20]],
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
    graph.add_node("bundle_and_save", bundle_and_save_node)
    graph.add_node("approval", approval_node)

    graph.add_edge(START, "load_artifacts")
    graph.add_edge("load_artifacts", "execute_task")

    graph.add_conditional_edges(
        "execute_task",
        route_task_iteration,
        {
            "next_task": "process_next",
            "completed": "bundle_and_save",
        },
    )

    graph.add_edge("process_next", "execute_task")
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
        interrupt_before=["approval"],
    )

    return compiled
