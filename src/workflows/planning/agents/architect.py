import json
import logging
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq

from src.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

ARCHITECT_SYSTEM_PROMPT = """You are an Architect agent for an AI Agent Factory.

Your role is to design the system architecture based on requirements, research findings, and selected patterns.

## Instructions:
1. Analyze requirements, research findings, and selected patterns
2. Design a clear system architecture with components and data flow
3. Reference how selected patterns will be implemented
4. Identify deployment considerations and risks
5. Keep the architecture practical and implementable

## Output Format (JSON):
{
  "architecture_md": "# Architecture Document\\n\\n## Overview\\n...",
  "architecture_json": {
    "overview": "High-level description",
    "components": [
      {
        "name": "ComponentName",
        "description": "What it does",
        "responsibilities": ["responsibility1"],
        "dependencies": ["other_component"]
      }
    ],
    "data_flow": [
      {
        "from": "SourceComponent",
        "to": "TargetComponent",
        "data": "What flows",
        "protocol": "How"
      }
    ],
    "patterns_implementation": {
      "pattern_name": "How it's implemented in this architecture"
    },
    "deployment": {
      "considerations": ["consideration1"],
      "infrastructure": ["infrastructure1"]
    },
    "risks": [
      {
        "risk": "Risk description",
        "mitigation": "How to mitigate"
      }
    ]
  }
}
"""


class ArchitectAgent:
    def __init__(self):
        self.llm = None
        if settings.GROQ_API_KEY:
            self.llm = ChatGroq(
                model=settings.LLM_MODEL,
                api_key=settings.GROQ_API_KEY,
                temperature=0.3,
            )

    async def design_architecture(self, state: dict) -> dict:
        requirements_md = state.get("requirements_md", "")
        requirements_json = state.get("requirements_json", {})
        selected_patterns = state.get("selected_patterns", [])
        research_findings = state.get("research_findings", [])

        if self.llm:
            result = await self._design_with_llm(
                requirements_md, requirements_json, selected_patterns, research_findings
            )
        else:
            result = self._design_without_llm(
                requirements_json, selected_patterns, research_findings
            )

        return {
            "architecture_md": result["architecture_md"],
            "architecture_json": result["architecture_json"],
            "current_phase": "architecture_designed",
        }

    async def _design_with_llm(
        self,
        requirements_md: str,
        requirements_json: dict,
        selected_patterns: list[dict],
        research_findings: list[dict],
    ) -> dict:
        patterns_text = "\n".join([
            f"- {p.get('name', 'Unknown')}: {p.get('rationale', '')}" for p in selected_patterns
        ])

        research_text = "\n".join([
            f"- [{f.get('source_type', 'unknown')}] {f.get('claim', '')[:200]}" for f in research_findings[:5]
        ])

        user_message = f"""## Requirements

{requirements_md[:2000]}

## Selected Patterns
{patterns_text}

## Research Findings
{research_text}

## Task
Design the system architecture. Return JSON with architecture_md and architecture_json fields."""

        try:
            response = await self.llm.ainvoke([
                SystemMessage(content=ARCHITECT_SYSTEM_PROMPT),
                HumanMessage(content=user_message),
            ])

            content = response.content
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]

            return json.loads(content.strip())
        except Exception as e:
            logger.warning("LLM architecture design failed, using fallback: %s", e)
            return self._design_without_llm(requirements_json, selected_patterns, research_findings)

    def _design_without_llm(
        self,
        requirements_json: dict,
        selected_patterns: list[dict],
        research_findings: list[dict],
    ) -> dict:
        frs = requirements_json.get("functional_requirements", [])
        pattern_names = [p.get("name", "Unknown") for p in selected_patterns]

        architecture_md = "# Architecture Document\n\n"
        architecture_md += "## Overview\n\n"
        architecture_md += "System designed to fulfill the project requirements using selected agentic patterns.\n\n"

        architecture_md += "## Components\n\n"
        components = []
        for fr in frs[:5]:
            comp_name = fr.get("title", "Component").replace(" ", "")
            components.append({
                "name": comp_name,
                "description": fr.get("content", "")[:200],
                "responsibilities": [fr.get("title", "")],
                "dependencies": [],
            })
            architecture_md += f"### {comp_name}\n{fr.get('content', '')[:200]}\n\n"

        architecture_md += "## Selected Patterns\n\n"
        for p in selected_patterns:
            architecture_md += f"- **{p.get('name', 'Unknown')}**: {p.get('rationale', '')}\n"

        architecture_json = {
            "overview": f"System implementing {len(frs)} functional requirements using {len(pattern_names)} patterns",
            "components": components,
            "data_flow": [
                {"from": "User", "to": "API", "data": "Requests", "protocol": "HTTP"},
                {"from": "API", "to": "Agents", "data": "Commands", "protocol": "Internal"},
            ],
            "patterns_implementation": {p: "Standard implementation" for p in pattern_names},
            "deployment": {
                "considerations": ["Authentication", "Error handling"],
                "infrastructure": ["SQLite", "ChromaDB", "File storage"],
            },
            "risks": [
                {"risk": "Integration complexity", "mitigation": "Incremental implementation"},
            ],
        }

        return {
            "architecture_md": architecture_md,
            "architecture_json": architecture_json,
        }


architect_agent = ArchitectAgent()
