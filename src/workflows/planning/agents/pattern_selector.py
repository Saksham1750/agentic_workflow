import json
import logging
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from src.services.pattern_service import pattern_service
from src.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

PATTERN_SELECTOR_SYSTEM_PROMPT = """You are a Pattern Selector agent for an AI Agent Factory.

Your role is to analyze project requirements and select the most appropriate agentic design patterns from the Knowledge Base.

## Instructions:
1. Analyze the requirements document carefully
2. Search the Pattern KB for patterns that match the project's needs
3. Select a MINIMAL set of patterns - only those truly needed
4. For each selected pattern, provide:
   - Pattern name
   - Rationale explaining WHY it was chosen
   - Which specific requirements it addresses
5. Do NOT over-select patterns. Fewer, well-justified patterns are better.

## Output Format (JSON):
{
  "selected_patterns": [
    {
      "name": "pattern_name",
      "rationale": "Why this pattern fits the project",
      "requirement_mapping": ["FR-001", "NFR-001"]
    }
  ],
  "overall_rationale": "Summary of selection strategy"
}
"""

class PatternSelectorAgent:
    def __init__(self):
        self.llm = None
        if settings.OPENAI_API_KEY:
            self.llm = ChatOpenAI(
                model="gpt-4o",
                api_key=settings.OPENAI_API_KEY,
                temperature=0.3,
            )

    async def select_patterns(self, state: dict) -> dict:
        requirements_md = state.get("requirements_md", "")
        requirements_json = state.get("requirements_json", {})
        project_id = state.get("project_id", "")

        search_query = self._build_search_query(requirements_json)
        
        kb_results = await pattern_service.search_patterns(
            query=search_query,
            n_results=8,
        )

        available_patterns = []
        for result in kb_results:
            meta = result.get("metadata", {})
            available_patterns.append({
                "name": meta.get("name", "Unknown"),
                "content": result.get("content", ""),
                "score": result.get("score", 0),
            })

        if self.llm:
            selected = await self._select_with_llm(
                requirements_md, requirements_json, available_patterns
            )
        else:
            selected = self._select_with_rules(requirements_json, available_patterns)

        return {
            "selected_patterns": selected["selected_patterns"],
            "pattern_rationale": selected.get("overall_rationale", ""),
            "current_phase": "patterns_selected",
        }

    def _build_search_query(self, requirements_json: dict) -> str:
        parts = []
        frs = requirements_json.get("functional_requirements", [])
        for fr in frs[:5]:
            parts.append(fr.get("title", ""))
            parts.append(fr.get("content", "")[:200])
        
        nfrs = requirements_json.get("non_functional_requirements", [])
        for nfr in nfrs[:3]:
            parts.append(nfr.get("title", ""))
        
        return " ".join(parts)[:500] if parts else "general agent pattern"

    async def _select_with_llm(
        self,
        requirements_md: str,
        requirements_json: dict,
        available_patterns: list[dict],
    ) -> dict:
        patterns_text = "\n\n".join([
            f"### {p['name']}\n{p['content'][:500]}" for p in available_patterns
        ])

        user_message = f"""## Project Requirements

{requirements_md[:3000]}

## Available Patterns from Knowledge Base

{patterns_text}

## Task
Select the minimal set of patterns needed for this project. Return JSON only."""

        try:
            response = await self.llm.ainvoke([
                SystemMessage(content=PATTERN_SELECTOR_SYSTEM_PROMPT),
                HumanMessage(content=user_message),
            ])

            content = response.content
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]

            return json.loads(content.strip())
        except Exception as e:
            logger.warning("LLM pattern selection failed, falling back to rules: %s", e)
            return self._select_with_rules(requirements_json, available_patterns)

    def _select_with_rules(
        self,
        requirements_json: dict,
        available_patterns: list[dict],
    ) -> dict:
        frs = requirements_json.get("functional_requirements", [])
        nfrs = requirements_json.get("non_functional_requirements", [])

        selected = []
        pattern_names = [p["name"].lower() for p in available_patterns]

        if any("multi" in fr.get("title", "").lower() or "agent" in fr.get("content", "").lower() for fr in frs):
            if "hierarchical" in " ".join(pattern_names):
                selected.append({
                    "name": "Hierarchical (Supervisor-Worker)",
                    "rationale": "Project requires multi-agent coordination",
                    "requirement_mapping": [fr.get("id", "") for fr in frs[:2]],
                })

        if any("search" in fr.get("content", "").lower() or "retrieve" in fr.get("content", "").lower() for fr in frs):
            if "rag" in " ".join(pattern_names):
                selected.append({
                    "name": "RAG (Retrieval-Augmented Generation)",
                    "rationale": "Project requires document retrieval and search",
                    "requirement_mapping": [fr.get("id", "") for fr in frs[:2]],
                })

        if any("reason" in fr.get("content", "").lower() or "decide" in fr.get("content", "").lower() for fr in frs):
            if "react" in " ".join(pattern_names):
                selected.append({
                    "name": "ReAct (Reasoning + Acting)",
                    "rationale": "Project requires reasoning and decision-making",
                    "requirement_mapping": [fr.get("id", "") for fr in frs[:2]],
                })

        if any("task" in fr.get("content", "").lower() for fr in frs):
            if "planner" in " ".join(pattern_names):
                selected.append({
                    "name": "Planner-Executor",
                    "rationale": "Project requires task planning and execution",
                    "requirement_mapping": [fr.get("id", "") for fr in frs[:2]],
                })

        if not selected and available_patterns:
            top = available_patterns[0]
            selected.append({
                "name": top["name"],
                "rationale": "Best matching pattern from Knowledge Base",
                "requirement_mapping": [],
            })

        return {
            "selected_patterns": selected[:5],
            "overall_rationale": "Selected based on requirement analysis and pattern matching",
        }


pattern_selector_agent = PatternSelectorAgent()
