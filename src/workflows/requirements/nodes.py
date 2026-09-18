import uuid
import logging

from sqlalchemy import select

from src.models.document import Document
from src.database import async_session_factory
from src.services.embedding_service import embedding_service
from src.services.rag_service import rag_service

logger = logging.getLogger(__name__)


async def document_ingestion_node(state: dict) -> dict:
    project_id = state["project_id"]

    async with async_session_factory() as db:
        result = await db.execute(
            select(Document).where(Document.project_id == project_id, Document.status == "ready")
        )
        docs = list(result.scalars().all())

    documents = []
    for doc in docs:
        sections = doc.sections_meta.get("sections", []) if doc.sections_meta else []
        documents.append({
            "document_id": doc.id,
            "filename": doc.filename,
            "content_type": doc.content_type,
            "section_count": len(sections),
            "sections": sections,
        })

    return {
        "documents": documents,
        "current_phase": "ingested",
    }


async def gap_analysis_node(state: dict) -> dict:
    documents = state.get("documents", [])
    feedback = state.get("feedback")

    doc_summaries = []
    for doc in documents:
        sections = doc.get("sections", [])
        content_preview = "\n".join(s.get("content", "")[:500] for s in sections[:3])
        doc_summaries.append(f"Document: {doc['filename']} ({doc['section_count']} sections)\n{content_preview}")

    document_context = "\n\n".join(doc_summaries) if doc_summaries else "No documents loaded."

    if feedback:
        document_context += f"\n\nPrevious feedback from reviewer:\n{feedback}"

    gaps_identified = []
    if not documents:
        gaps_identified.append("No input documents provided. Need BRD/PRD/TRD to proceed.")
    else:
        gaps_identified.extend([
            "Verify non-functional requirements (performance, security, scalability).",
            "Confirm acceptance criteria for each requirement.",
            "Validate integration points and external dependencies.",
            "Clarify deployment and environment requirements.",
        ])

    if feedback:
        gaps_identified.append(f"Incorporating reviewer feedback: {feedback}")

    return {
        "clarifications": [{"gap_id": str(uuid.uuid4()), "gaps": gaps_identified}],
        "current_phase": "gap_analysis",
    }


async def clarification_generator_node(state: dict) -> dict:
    from langgraph.types import interrupt

    clarifications = state.get("clarifications", [])
    round_num = state.get("clarification_round", 0)
    max_rounds = state.get("max_clarification_rounds", 3)

    if round_num >= max_rounds:
        return {
            "current_phase": "clarification_max_reached",
        }

    all_gaps = []
    for c in clarifications:
        all_gaps.extend(c.get("gaps", []))

    if not all_gaps:
        return {"current_phase": "no_clarifications_needed"}

    questions = []
    for i, gap in enumerate(all_gaps[:5]):
        questions.append({
            "question_id": str(uuid.uuid4()),
            "question": f"Please clarify: {gap}",
            "context": "This was identified during gap analysis of the uploaded documents.",
            "options": None,
        })

    answer = interrupt({
        "type": "clarification_request",
        "request_id": str(uuid.uuid4()),
        "questions": questions,
        "round": round_num + 1,
    })

    return {
        "clarifications": [*clarifications, {"answers": answer}],
        "clarification_round": round_num + 1,
        "current_phase": "clarification_complete",
    }


async def requirements_synthesizer_node(state: dict) -> dict:
    documents = state.get("documents", [])
    clarifications = state.get("clarifications", [])

    doc_sections = []
    for doc in documents:
        for section in doc.get("sections", []):
            doc_sections.append({
                "document": doc["filename"],
                "title": section.get("title", "Untitled"),
                "content": section.get("content", "")[:2000],
            })

    answers_context = ""
    for c in clarifications:
        if "answers" in c:
            answers_context += str(c["answers"]) + "\n"

    requirements_md = "# Requirements Document\n\n"
    requirements_md += "## Overview\n"
    requirements_md += "This document captures requirements derived from the uploaded documents and clarification responses.\n\n"

    requirements_md += "## Functional Requirements\n\n"
    for i, section in enumerate(doc_sections[:20], 1):
        requirements_md += f"### FR-{i:03d}: {section['title']}\n"
        requirements_md += f"**Source:** {section['document']}\n\n"
        requirements_md += f"{section['content']}\n\n"

    requirements_md += "## Non-Functional Requirements\n\n"
    requirements_md += "### NFR-001: Performance\nSystem shall respond within 2 seconds for standard operations.\n\n"
    requirements_md += "### NFR-002: Security\nAll data in transit shall be encrypted. Authentication required for all endpoints.\n\n"
    requirements_md += "### NFR-003: Scalability\nSystem shall support concurrent users as specified in the BRD.\n\n"

    if answers_context:
        requirements_md += "## Clarifications & Decisions\n\n"
        requirements_md += answers_context + "\n"

    requirements_json = {
        "version": "1.0",
        "functional_requirements": [
            {"id": f"FR-{i:03d}", "title": s["title"], "source": s["document"], "content": s["content"][:500]}
            for i, s in enumerate(doc_sections[:20], 1)
        ],
        "non_functional_requirements": [
            {"id": "NFR-001", "title": "Performance", "content": "2s response time"},
            {"id": "NFR-002", "title": "Security", "content": "Encrypted transit, auth required"},
            {"id": "NFR-003", "title": "Scalability", "content": "Concurrent user support"},
        ],
        "clarifications": [c for c in clarifications if "answers" in c],
    }

    return {
        "requirements_md": requirements_md,
        "requirements_json": requirements_json,
        "current_phase": "synthesized",
    }


async def validation_node(state: dict) -> dict:
    from langgraph.types import interrupt

    requirements_md = state.get("requirements_md", "")
    requirements_json = state.get("requirements_json", {})

    issues = []
    if not requirements_md:
        issues.append("No requirements document generated")
    if not requirements_json.get("functional_requirements"):
        issues.append("No functional requirements found")

    validation_result = {
        "valid": len(issues) == 0,
        "issues": issues,
        "functional_count": len(requirements_json.get("functional_requirements", [])),
        "nfr_count": len(requirements_json.get("non_functional_requirements", [])),
    }

    if issues:
        return {
            "validation_result": validation_result,
            "current_phase": "validation_failed",
        }

    approval = interrupt({
        "type": "approval_request",
        "run_id": state.get("run_id"),
        "artifact_summary": f"Requirements document with {validation_result['functional_count']} FRs and {validation_result['nfr_count']} NFRs",
        "requirements_preview": requirements_md[:2000],
    })

    if isinstance(approval, dict) and approval.get("approved"):
        return {
            "validation_result": {**validation_result, "approved": True},
            "current_phase": "approved",
        }
    else:
        feedback = approval.get("feedback", "No feedback provided") if isinstance(approval, dict) else str(approval)
        return {
            "feedback": feedback,
            "validation_result": {**validation_result, "approved": False},
            "current_phase": "rejected",
        }
