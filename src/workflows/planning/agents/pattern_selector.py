import json
import logging
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq

from src.services.pattern_service import pattern_service
from src.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

PATTERN_SELECTOR_SYSTEM_PROMPT = """You are a Pattern Selector agent for a software architecture system.

Your role is to analyze project requirements and select the most appropriate design patterns from the Knowledge Base.

## Step 1: Classify the Project Type
First, determine the project type:
- **agentic**: Requires AI agents, LLM reasoning, tool-use, autonomous decision-making, multi-agent coordination
- **traditional**: Standard software app — CRUD APIs, web apps, mobile backends, data pipelines, CLI tools
- **hybrid**: Combines traditional software with agentic/AI capabilities

## Step 2: Select Patterns
Based on the project type, select patterns from the Knowledge Base:
- For **agentic** projects: Select from agent patterns (ReAct, RAG, Planner-Executor, etc.)
- For **traditional** projects: Select from architectural patterns (MVC, Microservices, REST, Repository, etc.)
- For **hybrid** projects: Select from both categories as needed

## Instructions:
1. Select a MINIMAL set — only patterns truly needed
2. For each selected pattern, provide name, rationale, and which requirements it addresses
3. If the project is a simple CRUD app with no special needs, a single pattern (like MVC or REST) may suffice
4. Zero patterns is valid only for trivial projects (hello world, static pages)
5. Consider backend, frontend, database, and deployment patterns as needed

## Output Format (JSON):
{
  "project_type": "agentic|traditional|hybrid",
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
        if settings.GROQ_API_KEY:
            self.llm = ChatGroq(
                model=settings.LLM_MODEL,
                api_key=settings.GROQ_API_KEY,
                temperature=0.3,
            )

    async def select_patterns(self, state: dict) -> dict:
        requirements_md = state.get("requirements_md", "")
        requirements_json = state.get("requirements_json", {})
        project_id = state.get("project_id", "")
        run_id = state.get("run_id", "")

        search_query = self._build_search_query(requirements_json)

        kb_results = await pattern_service.search_patterns(
            query=search_query,
            n_results=12,
        )

        available_patterns = []
        for result in kb_results:
            meta = result.get("metadata", {})
            available_patterns.append({
                "name": meta.get("name", "Unknown"),
                "content": result.get("content", ""),
                "score": result.get("score", 0),
                "tags": meta.get("tags", []),
            })

        if self.llm:
            selected = await self._select_with_llm(
                requirements_md, requirements_json, available_patterns,
                run_id=run_id, project_id=project_id,
            )
        else:
            selected = self._select_with_rules(requirements_json, available_patterns)

        project_type = selected.get("project_type", "traditional")

        return {
            "selected_patterns": selected["selected_patterns"],
            "pattern_rationale": selected.get("overall_rationale", ""),
            "project_type": project_type,
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

        return " ".join(parts)[:500] if parts else "software architecture patterns"

    async def _select_with_llm(
        self,
        requirements_md: str,
        requirements_json: dict,
        available_patterns: list[dict],
        run_id: str = "",
        project_id: str = "",
    ) -> dict:
        patterns_text = "\n\n".join([
            f"### {p['name']}\n{p['content'][:500]}" for p in available_patterns
        ])

        user_message = f"""## Project Requirements

{requirements_md[:3000]}

## Available Patterns from Knowledge Base

{patterns_text}

## Task
1. Classify the project as agentic, traditional, or hybrid
2. Select the minimal set of patterns needed for this project
3. Return JSON only."""

        try:
            from src.observability.token_callback import TokenTrackingCallback
            callback = TokenTrackingCallback(run_id, project_id, "pattern_selector") if run_id and project_id else None
            config = {"callbacks": [callback]} if callback else {}
            response = await self.llm.ainvoke([
                SystemMessage(content=PATTERN_SELECTOR_SYSTEM_PROMPT),
                HumanMessage(content=user_message),
            ], config=config)

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

        all_text = " ".join([
            fr.get("title", "") + " " + fr.get("content", "")
            for fr in frs
        ]).lower() + " " + " ".join([
            nfr.get("title", "") + " " + nfr.get("content", "")
            for nfr in nfrs
        ]).lower()

        project_type = self._classify_project_type(all_text, frs)
        selected = []

        if project_type == "agentic":
            selected = self._select_agentic_patterns(all_text, frs, available_patterns)
        elif project_type == "traditional":
            selected = self._select_traditional_patterns(all_text, frs, available_patterns)
        else:
            selected = self._select_hybrid_patterns(all_text, frs, available_patterns)

        return {
            "project_type": project_type,
            "selected_patterns": selected[:8],
            "overall_rationale": f"Selected {len(selected)} patterns for {project_type} project",
        }

    def _classify_project_type(self, text: str, frs: list[dict]) -> str:
        agentic_keywords = [
            "agent", "llm", "ai", "reason", "decide", "autonom",
            "tool-use", "function-call", "rag", "retrieval", "multi-agent",
            "prompt", "chain", "inference", "model", "neural",
        ]
        traditional_keywords = [
            "crud", "rest", "api", "database", "web app", "mobile",
            "frontend", "backend", "server", "deploy", "microservice",
            "event", "message", "queue", "cache", "auth",
        ]

        agentic_score = sum(1 for kw in agentic_keywords if kw in text)
        traditional_score = sum(1 for kw in traditional_keywords if kw in text)

        has_agent_fr = any(
            "agent" in fr.get("content", "").lower() or "ai" in fr.get("content", "").lower()
            for fr in frs
        )

        if agentic_score >= 3 or has_agent_fr:
            return "agentic"
        elif traditional_score >= 2 and agentic_score == 0:
            return "traditional"
        elif agentic_score > 0 and traditional_score > 0:
            return "hybrid"
        else:
            return "traditional"

    def _select_agentic_patterns(self, text: str, frs: list[dict], available: list[dict]) -> list[dict]:
        selected = []
        pattern_map = {p["name"].lower(): p for p in available}

        if any(kw in text for kw in ["reason", "decide", "think"]):
            for name, p in pattern_map.items():
                if "react" in name:
                    selected.append({"name": p["name"], "rationale": "Requires multi-step reasoning", "requirement_mapping": []})
                    break

        if any(kw in text for kw in ["search", "retrieve", "knowledge", "document"]):
            for name, p in pattern_map.items():
                if "rag" in name:
                    selected.append({"name": p["name"], "rationale": "Requires document retrieval", "requirement_mapping": []})
                    break

        if any(kw in text for kw in ["multi", "agent", "collaborat"]):
            for name, p in pattern_map.items():
                if "hierarchical" in name or "multi-agent" in name:
                    selected.append({"name": p["name"], "rationale": "Requires multi-agent coordination", "requirement_mapping": []})
                    break

        if any(kw in text for kw in ["task", "plan", "decompos"]):
            for name, p in pattern_map.items():
                if "planner" in name:
                    selected.append({"name": p["name"], "rationale": "Requires task planning", "requirement_mapping": []})
                    break

        if any(kw in text for kw in ["tool", "api call", "external"]):
            for name, p in pattern_map.items():
                if "tool-use" in name:
                    selected.append({"name": p["name"], "rationale": "Requires external tool integration", "requirement_mapping": []})
                    break

        return selected

    def _select_traditional_patterns(self, text: str, frs: list[dict], available: list[dict]) -> list[dict]:
        selected = []
        pattern_map = {p["name"].lower(): p for p in available}

        if any(kw in text for kw in ["crud", "rest", "api", "http", "endpoint"]):
            for name, p in pattern_map.items():
                if "rest" in name or "mvc" in name:
                    selected.append({"name": p["name"], "rationale": "Standard REST API architecture", "requirement_mapping": []})
                    break

        if any(kw in text for kw in ["microservice", "distributed", "scale", "independent"]):
            for name, p in pattern_map.items():
                if "microservice" in name:
                    selected.append({"name": p["name"], "rationale": "Requires distributed architecture", "requirement_mapping": []})
                    break

        if any(kw in text for kw in ["event", "real-time", "async", "message", "publish"]):
            for name, p in pattern_map.items():
                if "event-driven" in name or "event" in name:
                    selected.append({"name": p["name"], "rationale": "Requires event-driven processing", "requirement_mapping": []})
                    break

        if any(kw in text for kw in ["database", "persist", "store", "repository"]):
            for name, p in pattern_map.items():
                if "repository" in name:
                    selected.append({"name": p["name"], "rationale": "Data access abstraction", "requirement_mapping": []})
                    break

        if any(kw in text for kw in ["frontend", "spa", "react", "vue", "browser"]):
            for name, p in pattern_map.items():
                if "spa" in name or "frontend" in name:
                    selected.append({"name": p["name"], "rationale": "Frontend application architecture", "requirement_mapping": []})
                    break

        if any(kw in text for kw in ["mobile", "ios", "android"]):
            for name, p in pattern_map.items():
                if "bff" in name or "rest" in name:
                    selected.append({"name": p["name"], "rationale": "Mobile API architecture", "requirement_mapping": []})
                    break

        if not selected:
            for name, p in pattern_map.items():
                if "mvc" in name or "layered" in name:
                    selected.append({"name": p["name"], "rationale": "Default layered architecture", "requirement_mapping": []})
                    break

        return selected

    def _select_hybrid_patterns(self, text: str, frs: list[dict], available: list[dict]) -> list[dict]:
        selected = []
        selected.extend(self._select_traditional_patterns(text, frs, available))
        selected.extend(self._select_agentic_patterns(text, frs, available))
        return selected


pattern_selector_agent = PatternSelectorAgent()
