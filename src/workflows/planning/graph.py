import logging
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt

from src.workflows.planning.state import PlanningState
from src.workflows.planning.agents.pattern_selector import pattern_selector_agent
from src.workflows.planning.agents.researcher import researcher_agent
from src.workflows.planning.agents.architect import architect_agent
from src.workflows.planning.agents.planner import planner_agent
from src.workflows.planning.agents.critic import critic_agent
from src.workflows.planning.nodes.router import complexity_router, route_by_complexity

logger = logging.getLogger(__name__)


async def load_requirements_node(state: dict) -> dict:
    from src.services.artifact_service import artifact_service
    from src.database import async_session_factory
    from src.models.run import Run
    from sqlalchemy import select

    project_id = state.get("project_id", "")

    async with async_session_factory() as db:
        result = await db.execute(
            select(Run).where(
                Run.project_id == project_id,
                Run.workflow_type == "requirements",
                Run.status == "completed",
            ).order_by(Run.created_at.desc()).limit(1)
        )
        req_run = result.scalar_one_or_none()

    if req_run:
        requirements_md, requirements_json = await artifact_service.load_requirements(
            project_id=project_id,
            run_id=req_run.id,
        )
    else:
        requirements_md, requirements_json = None, None

    return {
        "requirements_md": requirements_md,
        "requirements_json": requirements_json or {},
        "current_phase": "requirements_loaded",
    }


async def pattern_selection_node(state: dict) -> dict:
    return await pattern_selector_agent.select_patterns(state)


async def research_node(state: dict) -> dict:
    return await researcher_agent.research(state)


async def architecture_node(state: dict) -> dict:
    return await architect_agent.design_architecture(state)


async def lightweight_planning_node(state: dict) -> dict:
    return await planner_agent.create_task_plan(state)


async def full_planning_node(state: dict) -> dict:
    result = await planner_agent.create_task_plan(state)
    return result


async def validation_node(state: dict) -> dict:
    result = await critic_agent.validate_plan(state)
    result["iteration_count"] = state.get("iteration_count", 0) + 1
    return result


async def approval_node(state: dict) -> dict:
    from langgraph.types import interrupt

    tasks = state.get("tasks", [])
    validation = state.get("task_validation", {})

    approval = interrupt({
        "type": "approval_request",
        "run_id": state.get("run_id"),
        "task_count": len(tasks),
        "validation_score": validation.get("score", 0),
        "tasks_summary": [{"id": t.get("task_id"), "title": t.get("title")} for t in tasks[:10]],
    })

    if isinstance(approval, dict) and approval.get("approved"):
        return {
            "approval_result": {"approved": True},
            "current_phase": "approved",
        }
    else:
        feedback = approval.get("feedback", "No feedback provided") if isinstance(approval, dict) else str(approval)
        return {
            "feedback": feedback,
            "approval_result": {"approved": False, "feedback": feedback},
            "current_phase": "rejected",
        }


def route_after_validation(state: dict) -> str:
    validation = state.get("task_validation", {})
    iteration = state.get("iteration_count", 0)
    max_iter = state.get("max_iterations", 3)

    if validation and validation.get("valid", False):
        return "approval"

    if iteration >= max_iter:
        return "approval"

    return "revise"


def route_after_approval(state: dict) -> str:
    phase = state.get("current_phase", "")
    if phase == "rejected":
        return "planner_critic"
    return END


async def save_artifacts_node(state: dict) -> dict:
    from src.services.artifact_service import artifact_service

    project_id = state.get("project_id", "")
    run_id = state.get("run_id", "")

    try:
        await artifact_service.save_planning_artifacts(
            project_id=project_id,
            run_id=run_id,
            selected_patterns=state.get("selected_patterns", []),
            research_findings=state.get("research_findings", []),
            architecture_md=state.get("architecture_md", ""),
            architecture_json=state.get("architecture_json", {}),
            tasks=state.get("tasks", []),
            task_validation=state.get("task_validation", {}),
        )
    except Exception as e:
        logger.warning("Failed to save planning artifacts: %s", e)

    return state


async def build_planning_graph(checkpointer=None):
    graph = StateGraph(PlanningState)

    graph.add_node("load_requirements", load_requirements_node)
    graph.add_node("complexity_router", complexity_router)
    graph.add_node("pattern_selection", pattern_selection_node)
    graph.add_node("research", research_node)
    graph.add_node("architecture", architecture_node)
    graph.add_node("lightweight_planning", lightweight_planning_node)
    graph.add_node("full_planning", full_planning_node)
    graph.add_node("validation", validation_node)
    graph.add_node("save_artifacts", save_artifacts_node)
    graph.add_node("approval", approval_node)

    graph.add_edge(START, "load_requirements")
    graph.add_edge("load_requirements", "complexity_router")
    graph.add_edge("complexity_router", "pattern_selection")
    graph.add_edge("pattern_selection", "research")
    graph.add_edge("research", "architecture")

    graph.add_conditional_edges(
        "architecture",
        route_by_complexity,
        {
            "lightweight_path": "lightweight_planning",
            "full_path": "full_planning",
        },
    )

    graph.add_edge("lightweight_planning", "validation")
    graph.add_edge("full_planning", "validation")

    graph.add_conditional_edges(
        "validation",
        route_after_validation,
        {
            "approval": "save_artifacts",
            "revise": "full_planning",
        },
    )

    graph.add_edge("save_artifacts", "approval")

    graph.add_conditional_edges(
        "approval",
        route_after_approval,
        {
            "planner_critic": "full_planning",
            END: END,
        },
    )

    compiled = graph.compile(
        checkpointer=checkpointer,
    )

    return compiled
