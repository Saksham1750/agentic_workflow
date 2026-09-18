from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.auth.dependencies import get_current_user
from src.websockets.hitl import websocket_hitl_endpoint

router = APIRouter(tags=["workflows"])


@router.get("/workflows")
async def list_workflows(user_id: str = Depends(get_current_user)):
    return {
        "workflows": [
            {
                "name": "requirements",
                "description": "Requirements gathering with reflection and HITL",
                "status": "available",
                "phases": ["document_ingestion", "gap_analysis", "clarification", "synthesis", "validation"],
            },
            {
                "name": "planning",
                "description": "Combined project and code planning with pattern selection, research, and architecture design",
                "status": "available",
                "phases": [
                    "load_requirements",
                    "complexity_routing",
                    "pattern_selection",
                    "research",
                    "architecture",
                    "planning",
                    "validation",
                    "approval",
                ],
            },
            {
                "name": "codegen",
                "description": "Code generation with developer agent, parallel reviewer sub-agents, and bundle download",
                "status": "available",
                "phases": [
                    "load_artifacts",
                    "execute_task",
                    "review_code",
                    "bundle_and_save",
                    "approval",
                ],
            },
        ]
    }


@router.get("/workflows/{workflow_name}/graph")
async def get_workflow_graph(
    workflow_name: str,
    user_id: str = Depends(get_current_user),
):
    if workflow_name == "requirements":
        return {
            "name": "requirements",
            "nodes": [
                "document_ingestion",
                "gap_analysis",
                "clarification_generator",
                "requirements_synthesizer",
                "validation",
            ],
            "edges": [
                ("START", "document_ingestion"),
                ("document_ingestion", "gap_analysis"),
                ("gap_analysis", "clarification_generator"),
                ("clarification_generator", "requirements_synthesizer"),
                ("requirements_synthesizer", "validation"),
                ("validation", "END"),
                ("validation", "gap_analysis"),
            ],
            "interrupt_before": ["clarification_generator", "validation"],
        }
    elif workflow_name == "planning":
        return {
            "name": "planning",
            "nodes": [
                "load_requirements",
                "complexity_router",
                "pattern_selection",
                "research",
                "architecture",
                "lightweight_planning",
                "full_planning",
                "validation",
                "approval",
            ],
            "edges": [
                ("START", "load_requirements"),
                ("load_requirements", "complexity_router"),
                ("complexity_router", "pattern_selection"),
                ("pattern_selection", "research"),
                ("research", "architecture"),
                ("architecture", "lightweight_planning"),
                ("architecture", "full_planning"),
                ("lightweight_planning", "validation"),
                ("full_planning", "validation"),
                ("validation", "approval"),
                ("validation", "full_planning"),
                ("approval", "END"),
                ("approval", "full_planning"),
            ],
            "interrupt_before": ["approval"],
            "subgraphs": {
                "research": ["doc_rag", "kb_rag", "web_search", "merge"],
                "planner_critic": ["planner", "critic"],
            },
        }
    elif workflow_name == "codegen":
        return {
            "name": "codegen",
            "nodes": [
                "load_artifacts",
                "execute_task",
                "process_next",
                "bundle_and_save",
                "approval",
            ],
            "edges": [
                ("START", "load_artifacts"),
                ("load_artifacts", "execute_task"),
                ("execute_task", "process_next"),
                ("execute_task", "bundle_and_save"),
                ("process_next", "execute_task"),
                ("bundle_and_save", "approval"),
                ("approval", "END"),
                ("approval", "execute_task"),
            ],
            "interrupt_before": ["approval"],
            "subgraphs": {
                "task_subgraph": ["developer", "parallel_reviewers", "reduce_reviews"],
            },
        }
    return {"error": "Unknown workflow"}
