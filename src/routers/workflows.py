from fastapi import APIRouter, Depends
from fastapi.responses import Response
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
                    "pattern_selection",
                    "research",
                    "architecture",
                    "planning",
                    "validation",
                    "save_artifacts",
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


async def _build_workflow_graph(workflow_name: str):
    from src.workflows.checkpointer import get_checkpointer

    checkpointer = await get_checkpointer()

    if workflow_name == "requirements":
        from src.workflows.requirements.graph import build_requirements_graph
        return await build_requirements_graph(checkpointer=checkpointer)
    elif workflow_name == "planning":
        from src.workflows.planning.graph import build_planning_graph
        return await build_planning_graph(checkpointer=checkpointer)
    elif workflow_name == "codegen":
        from src.workflows.codegen.graph import build_codegen_graph
        return await build_codegen_graph(checkpointer=checkpointer)
    return None


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
                "pattern_selection",
                "research",
                "architecture",
                "planning",
                "validation",
                "save_artifacts",
                "approval",
            ],
            "edges": [
                ("START", "load_requirements"),
                ("load_requirements", "pattern_selection"),
                ("pattern_selection", "research"),
                ("research", "architecture"),
                ("architecture", "planning"),
                ("planning", "validation"),
                ("validation", "save_artifacts"),
                ("validation", "planning"),
                ("save_artifacts", "approval"),
                ("approval", "END"),
                ("approval", "planning"),
            ],
            "interrupt_before": ["approval"],
            "subgraphs": {
                "research": ["doc_rag", "kb_rag", "web_search", "merge"],
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


@router.get("/workflows/{workflow_name}/graph.png")
async def get_workflow_graph_png(
    workflow_name: str,
    user_id: str = Depends(get_current_user),
):
    graph = await _build_workflow_graph(workflow_name)
    if not graph:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Unknown workflow: {workflow_name}")

    try:
        png_bytes = graph.get_graph().draw_mermaid_png()
        return Response(content=png_bytes, media_type="image/png")
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=f"Failed to render graph: {e}")


@router.get("/workflows/{workflow_name}/graph.mermaid")
async def get_workflow_graph_mermaid(
    workflow_name: str,
    user_id: str = Depends(get_current_user),
):
    graph = await _build_workflow_graph(workflow_name)
    if not graph:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Unknown workflow: {workflow_name}")

    try:
        mermaid_text = graph.get_graph().draw_mermaid()
        return Response(content=mermaid_text, media_type="text/plain")
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=f"Failed to render mermaid: {e}")
