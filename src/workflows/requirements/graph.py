import logging
from langgraph.graph import StateGraph, START, END

from src.workflows.requirements.state import RequirementsState
from src.workflows.requirements.nodes import (
    document_ingestion_node,
    gap_analysis_node,
    clarification_generator_node,
    requirements_synthesizer_node,
    validation_node,
)

logger = logging.getLogger(__name__)


def route_after_validation(state: dict) -> str:
    phase = state.get("current_phase", "")
    if phase == "rejected":
        return "gap_analysis"
    return END


async def build_requirements_graph(checkpointer=None):
    graph = StateGraph(RequirementsState)

    graph.add_node("document_ingestion", document_ingestion_node)
    graph.add_node("gap_analysis", gap_analysis_node)
    graph.add_node("clarification_generator", clarification_generator_node)
    graph.add_node("requirements_synthesizer", requirements_synthesizer_node)
    graph.add_node("validation", validation_node)

    graph.add_edge(START, "document_ingestion")
    graph.add_edge("document_ingestion", "gap_analysis")
    graph.add_edge("gap_analysis", "clarification_generator")
    graph.add_edge("clarification_generator", "requirements_synthesizer")
    graph.add_edge("requirements_synthesizer", "validation")

    graph.add_conditional_edges(
        "validation",
        route_after_validation,
        {"gap_analysis": "gap_analysis", END: END},
    )

    compiled = graph.compile(
        checkpointer=checkpointer,
        interrupt_before=["clarification_generator", "validation"],
    )

    return compiled
