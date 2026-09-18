import logging
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from src.services.rag_service import rag_service
from src.services.pattern_service import pattern_service
from src.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

RESEARCHER_SYSTEM_PROMPT = """You are a Researcher agent for an AI Agent Factory.

Your role is to gather information from multiple sources and synthesize findings with proper citations.

## Sources:
1. [doc:section] - From uploaded project documents
2. [kb:pattern] - From Pattern Knowledge Base
3. [web:url] - From web search results
4. [llm] - From your own knowledge

## Instructions:
1. Gather information from all available sources
2. Synthesize findings into coherent research points
3. EVERY claim MUST include a citation tag indicating its source
4. Prioritize document and KB sources over web search
5. Flag any conflicting information between sources

## Output Format (JSON):
{
  "findings": [
    {
      "id": "finding_001",
      "claim": "The research finding statement",
      "source_type": "doc|kb|web|llm",
      "source_reference": "specific reference",
      "confidence": "high|medium|low"
    }
  ],
  "synthesis": "Overall synthesis of findings",
  "gaps": ["Areas where more research is needed"]
}
"""


class ResearcherAgent:
    def __init__(self):
        self.llm = None
        if settings.OPENAI_API_KEY:
            self.llm = ChatOpenAI(
                model="gpt-4o",
                api_key=settings.OPENAI_API_KEY,
                temperature=0.3,
            )
        self._ddgs = None

    def _get_ddgs(self):
        if self._ddgs is None:
            try:
                from duckduckgo_search import DDGS
                self._ddgs = DDGS()
            except ImportError:
                logger.warning("duckduckgo_search not installed, web search disabled")
                return None
        return self._ddgs

    async def research(self, state: dict) -> dict:
        project_id = state.get("project_id", "")
        requirements_json = state.get("requirements_json", {})
        selected_patterns = state.get("selected_patterns", [])

        doc_findings = await self._research_documents(project_id, requirements_json)
        kb_findings = await self._research_knowledge_base(requirements_json, selected_patterns)
        web_findings = await self._research_web(requirements_json)

        all_findings = doc_findings + kb_findings + web_findings

        if self.llm:
            synthesized = await self._synthesize_with_llm(all_findings, requirements_json)
        else:
            synthesized = self._synthesize_without_llm(all_findings)

        return {
            "research_findings": synthesized["findings"],
            "research_log": [
                {
                    "source_type": f["source_type"],
                    "source_reference": f.get("source_reference", ""),
                    "claim": f["claim"],
                }
                for f in synthesized["findings"]
            ],
            "current_phase": "research_complete",
        }

    async def _research_documents(self, project_id: str, requirements_json: dict) -> list[dict]:
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
                    "id": f"doc_finding_{i+1}",
                    "claim": result.get("content", "")[:500],
                    "source_type": "doc",
                    "source_reference": f"Document section {result.get('section_id', 'unknown')}",
                    "confidence": "high",
                })
        except Exception as e:
            logger.warning("Document research failed: %s", e)

        return findings

    async def _research_knowledge_base(
        self,
        requirements_json: dict,
        selected_patterns: list[dict],
    ) -> list[dict]:
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
                    "id": f"kb_finding_{i+1}",
                    "claim": result.get("content", "")[:500],
                    "source_type": "kb",
                    "source_reference": f"Pattern: {meta.get('name', 'unknown')}",
                    "confidence": "high",
                })
        except Exception as e:
            logger.warning("KB research failed: %s", e)

        return findings

    async def _research_web(self, requirements_json: dict) -> list[dict]:
        findings = []
        try:
            ddgs = self._get_ddgs()
            if ddgs is None:
                return findings

            frs = requirements_json.get("functional_requirements", [])
            query_terms = [fr.get("title", "") for fr in frs[:2]]
            query = " ".join(query_terms)[:100] if query_terms else "software architecture best practices"

            if not query.strip():
                return findings

            results = ddgs.text(query, max_results=3)

            for i, result in enumerate(results):
                findings.append({
                    "id": f"web_finding_{i+1}",
                    "claim": result.get("body", "")[:500],
                    "source_type": "web",
                    "source_reference": result.get("href", ""),
                    "confidence": "medium",
                })
        except Exception as e:
            logger.warning("Web research failed: %s", e)

        return findings

    async def _synthesize_with_llm(
        self,
        findings: list[dict],
        requirements_json: dict,
    ) -> dict:
        findings_text = "\n\n".join([
            f"### {f['id']} [{f['source_type']}]\n{f['claim']}" for f in findings
        ])

        user_message = f"""## Research Findings

{findings_text}

## Requirements Summary
{str(requirements_json)[:2000]}

## Task
Synthesize these findings into a coherent research summary. Ensure every claim has a citation. Return JSON only."""

        try:
            response = await self.llm.ainvoke([
                SystemMessage(content=RESEARCHER_SYSTEM_PROMPT),
                HumanMessage(content=user_message),
            ])

            content = response.content
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]

            return json.loads(content.strip())
        except Exception as e:
            logger.warning("LLM synthesis failed, using basic synthesis: %s", e)
            return self._synthesize_without_llm(findings)

    def _synthesize_without_llm(self, findings: list[dict]) -> dict:
        return {
            "findings": findings[:10],
            "synthesis": f"Research gathered from {len(findings)} sources across documents, knowledge base, and web.",
            "gaps": ["Additional research may be needed for implementation details"],
        }


researcher_agent = ResearcherAgent()
