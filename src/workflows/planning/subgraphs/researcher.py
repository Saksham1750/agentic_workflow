import logging
from typing import Annotated, TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages

from src.services.rag_service import rag_service
from src.services.pattern_service import pattern_service
from src.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class ResearcherState(TypedDict):
    project_id: str
    requirements_json: dict
    selected_patterns: list[dict]
    doc_findings: list[dict]
    kb_findings: list[dict]
    web_findings: list[dict]
    all_findings: list[dict]


async def doc_rag_node(state: dict) -> dict:
    project_id = state.get("project_id", "")
    requirements_json = state.get("requirements_json", {})

    findings = []
    try:
        frs = requirements_json.get("functional_requirements", [])
        query_terms = [fr.get("title", "") for fr in frs[:3]]
        query = " ".join(query_terms)[:200] if query_terms else "project requirements"

        results = await rag_service.query_documents(
            project_id=project_id,
            query=query,
            n_results=5,
        )

        for i, result in enumerate(results):
            findings.append({
                "id": f"doc_{i+1}",
                "claim": result.get("content", "")[:500],
                "source_type": "doc",
                "source_reference": f"Document section {result.get('section_id', 'unknown')}",
                "confidence": "high",
            })
    except Exception as e:
        logger.warning("Document RAG failed: %s", e)

    return {"doc_findings": findings}


async def kb_rag_node(state: dict) -> dict:
    requirements_json = state.get("requirements_json", {})
    selected_patterns = state.get("selected_patterns", [])

    findings = []
    try:
        pattern_names = [p.get("name", "") for p in selected_patterns]
        query = " ".join(pattern_names)[:200] if pattern_names else "agentic design patterns"

        results = await pattern_service.search_patterns(
            query=query,
            n_results=5,
        )

        for i, result in enumerate(results):
            meta = result.get("metadata", {})
            findings.append({
                "id": f"kb_{i+1}",
                "claim": result.get("content", "")[:500],
                "source_type": "kb",
                "source_reference": f"Pattern: {meta.get('name', 'unknown')}",
                "confidence": "high",
            })
    except Exception as e:
        logger.warning("KB RAG failed: %s", e)

    return {"kb_findings": findings}


async def web_search_node(state: dict) -> dict:
    requirements_json = state.get("requirements_json", {})

    findings = []
    try:
        from duckduckgo_search import DDGS
        ddgs = DDGS()

        frs = requirements_json.get("functional_requirements", [])
        query_terms = [fr.get("title", "") for fr in frs[:2]]
        query = " ".join(query_terms)[:100] if query_terms else "software architecture best practices"

        if query.strip():
            results = ddgs.text(query, max_results=3)

            for i, result in enumerate(results):
                findings.append({
                    "id": f"web_{i+1}",
                    "claim": result.get("body", "")[:500],
                    "source_type": "web",
                    "source_reference": result.get("href", ""),
                    "confidence": "medium",
                })
    except Exception as e:
        logger.warning("Web search failed: %s", e)

    return {"web_findings": findings}


def merge_findings(state: dict) -> dict:
    doc = state.get("doc_findings", [])
    kb = state.get("kb_findings", [])
    web = state.get("web_findings", [])

    all_findings = doc + kb + web

    return {
        "all_findings": all_findings,
        "current_phase": "research_complete",
    }


def build_researcher_subgraph():
    graph = StateGraph(ResearcherState)

    graph.add_node("doc_rag", doc_rag_node)
    graph.add_node("kb_rag", kb_rag_node)
    graph.add_node("web_search", web_search_node)
    graph.add_node("merge", merge_findings)

    graph.add_edge(START, "doc_rag")
    graph.add_edge(START, "kb_rag")
    graph.add_edge(START, "web_search")

    graph.add_edge("doc_rag", "merge")
    graph.add_edge("kb_rag", "merge")
    graph.add_edge("web_search", "merge")

    graph.add_edge("merge", END)

    return graph.compile()
