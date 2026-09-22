import uuid
import json
import logging

from sqlalchemy import select

from src.config import get_settings
from src.models.document import Document
from src.database import async_session_factory
from src.services.embedding_service import embedding_service
from src.services.rag_service import rag_service
from src.observability.tracing import traced_node

logger = logging.getLogger(__name__)
settings = get_settings()


@traced_node("document_ingestion")
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


@traced_node("gap_analysis")
async def gap_analysis_node(state: dict) -> dict:
    documents = state.get("documents", [])
    feedback = state.get("feedback")
    project_id = state.get("project_id", "")

    if not documents:
        gaps_identified = ["No input documents provided. Need BRD/PRD/TRD to proceed."]
        if feedback:
            gaps_identified.append(f"Incorporating reviewer feedback: {feedback}")
        return {
            "clarifications": [{"gap_id": str(uuid.uuid4()), "gaps": gaps_identified}],
            "current_phase": "gap_analysis",
        }

    GAP_CATEGORIES = [
        {
            "id": "functional_requirements",
            "name": "Functional Requirements",
            "query": "functional requirements user stories features capabilities what the system should do",
            "threshold": 0.8,
        },
        {
            "id": "non_functional_requirements",
            "name": "Non-Functional Requirements",
            "query": "non-functional requirements performance security scalability availability reliability",
            "threshold": 0.8,
        },
        {
            "id": "user_personas",
            "name": "User Personas / Roles",
            "query": "user personas roles actors stakeholders target users who will use the system",
            "threshold": 0.75,
        },
        {
            "id": "deployment",
            "name": "Deployment & Infrastructure",
            "query": "deployment infrastructure hosting environment production setup devops",
            "threshold": 0.75,
        },
        {
            "id": "integration",
            "name": "Integration Points & External Dependencies",
            "query": "integration API external services third-party dependencies microservices",
            "threshold": 0.75,
        },
        {
            "id": "acceptance_criteria",
            "name": "Acceptance Criteria & Success Metrics",
            "query": "acceptance criteria success metrics definition of done testing validation",
            "threshold": 0.8,
        },
    ]

    gaps_identified = []

    for category in GAP_CATEGORIES:
        try:
            results = await embedding_service.query(
                project_id=project_id,
                query_text=category["query"],
                n_results=1,
            )
            if results:
                best_distance = results[0]["score"]
                if best_distance > category["threshold"]:
                    gaps_identified.append(
                        f"{category['name']} — appears to be missing or insufficiently covered in the uploaded documents "
                        f"(best match distance: {best_distance:.2f}, threshold: {category['threshold']})"
                    )
            else:
                gaps_identified.append(
                    f"{category['name']} — no matching content found in uploaded documents"
                )
        except Exception as e:
            logger.warning(
                "Vector search failed for gap category '%s': %s. Assuming gap exists.",
                category["id"],
                e,
            )
            gaps_identified.append(
                f"{category['name']} — could not verify coverage (search failed)"
            )

    if feedback:
        gaps_identified.append(f"Incorporating reviewer feedback: {feedback}")

    if not gaps_identified:
        gaps_identified.append(
            "All key sections (requirements, personas, deployment, integrations, "
            "acceptance criteria) appear to be covered in the uploaded documents."
        )

    return {
        "clarifications": [{"gap_id": str(uuid.uuid4()), "gaps": gaps_identified}],
        "current_phase": "gap_analysis",
    }


CLARIFICATION_SYSTEM_PROMPT = """You are a Requirements Analyst for a software project.

Your role is to convert raw gap-analysis findings into clear, natural clarification questions for the project owner.

## Instructions:
1. Read the list of gaps and the document section titles provided
2. For each gap, write a concise, professional question that a non-technical stakeholder can understand
3. Reference what IS already in the documents where relevant (e.g., "Your BRD mentions X, but doesn't specify Y...")
4. Do NOT expose internal scoring details, thresholds, or technical metadata
5. Each question should be self-contained — the reader should not need other context
6. If all gaps are covered, return an empty questions list

## Output Format (JSON):
{
  "questions": [
    {
      "question": "Natural language question text",
      "context": "Brief context about why this matters for the project"
    }
  ]
}
"""


def _generate_questions_without_llm(gaps: list[str]) -> list[dict]:
    friendly_names = {
        "Functional Requirements": "functional requirements (features and capabilities)",
        "Non-Functional Requirements": "non-functional requirements (performance, security, scalability)",
        "User Personas / Roles": "target user personas and roles",
        "Deployment & Infrastructure": "deployment and infrastructure details",
        "Integration Points & External Dependencies": "integration points with external services",
        "Acceptance Criteria & Success Metrics": "acceptance criteria and success metrics",
    }

    questions = []
    for gap in gaps:
        category_name = gap.split("—")[0].strip() if "—" in gap else gap.split(":")[0].strip()
        friendly = friendly_names.get(category_name, category_name.lower())

        if "no input documents" in gap.lower():
            questions.append({
                "question": "No documents were uploaded. Please upload a BRD, PRD, or TRD before we can proceed with requirements gathering.",
                "context": "Documents are needed to extract and validate requirements.",
            })
        elif "no matching content" in gap or "could not verify" in gap:
            questions.append({
                "question": f"The uploaded documents don't appear to contain information about {friendly}. Could you provide details on this topic?",
                "context": f"This section was not found in the uploaded documents.",
            })
        elif "missing or insufficiently" in gap or "insufficiently covered" in gap:
            questions.append({
                "question": f"The {friendly} section in your documents appears thin or incomplete. Could you expand on this or confirm the details?",
                "context": f"Some content was found but it may not be detailed enough for downstream planning.",
            })
        elif "Incorporating reviewer feedback" in gap:
            questions.append({
                "question": f"Additional feedback received: {gap.split(':', 1)[-1].strip() if ':' in gap else gap}. Please address this.",
                "context": "This feedback was raised during a previous review cycle.",
            })
        else:
            questions.append({
                "question": f"Please clarify or expand on: {friendly}",
                "context": "This was flagged during document analysis.",
            })

    return questions


@traced_node("clarification_generator")
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

    documents = state.get("documents", [])
    section_titles = []
    for doc in documents:
        for section in doc.get("sections", []):
            section_titles.append(section.get("title", ""))

    questions_data = None

    if settings.GROQ_API_KEY:
        try:
            from langchain_groq import ChatGroq
            from langchain_core.messages import HumanMessage, SystemMessage
            from src.observability.token_callback import TokenTrackingCallback

            llm = ChatGroq(
                model=settings.LLM_MODEL,
                api_key=settings.GROQ_API_KEY,
                temperature=0.3,
            )

            gaps_text = "\n".join(f"- {g}" for g in all_gaps[:5])
            titles_text = ", ".join(section_titles[:30]) if section_titles else "No section titles available"

            user_message = f"""## Gaps Identified
{gaps_text}

## Document Section Titles Found
{titles_text}

## Task
Convert these gaps into natural clarification questions. Return JSON only."""

            run_id = state.get("run_id", "")
            project_id = state.get("project_id", "")
            callback = TokenTrackingCallback(run_id, project_id, "clarification_generator") if run_id and project_id else None
            config = {"callbacks": [callback]} if callback else {}

            response = await llm.ainvoke([
                SystemMessage(content=CLARIFICATION_SYSTEM_PROMPT),
                HumanMessage(content=user_message),
            ], config=config)

            content = response.content
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]

            questions_data = json.loads(content.strip())
        except Exception as e:
            logger.warning("LLM question generation failed, using template fallback: %s", e)
            questions_data = None

    if not questions_data:
        questions_data = {"questions": _generate_questions_without_llm(all_gaps[:5])}

    questions = []
    for q in questions_data.get("questions", []):
        questions.append({
            "question_id": str(uuid.uuid4()),
            "question": q.get("question", "Please clarify the identified gap."),
            "context": q.get("context", "This was identified during gap analysis of the uploaded documents."),
            "options": None,
        })

    if not questions:
        return {"current_phase": "no_clarifications_needed"}

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


@traced_node("requirements_synthesizer")
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


@traced_node("validation")
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
