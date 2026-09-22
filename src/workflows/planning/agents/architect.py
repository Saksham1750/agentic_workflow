import json
import logging
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq

from src.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

ARCHITECT_SYSTEM_PROMPT = """You are a Software Architect agent.

Your role is to design the system architecture based on requirements, research findings, and selected patterns.

## Instructions:
1. Analyze requirements, research findings, and selected patterns
2. Design a clear system architecture with components and data flow
3. Reference how selected patterns will be implemented
4. Identify deployment considerations and risks
5. Keep the architecture practical and implementable

## For Agentic Projects:
- Design agent topologies (single agent, multi-agent, hierarchical)
- Include LLM integration, tool connections, and reasoning loops
- Consider prompt management and context handling

## For Traditional Projects:
- Design standard software architectures (layered, MVC, microservices, event-driven)
- Include API layer, business logic, data access, and storage
- Consider scaling, security, and deployment patterns

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
        project_type = state.get("project_type", "traditional")
        feedback = state.get("feedback")
        run_id = state.get("run_id", "")
        project_id = state.get("project_id", "")

        if self.llm:
            result = await self._design_with_llm(
                requirements_md, requirements_json, selected_patterns, research_findings,
                project_type=project_type, feedback=feedback, run_id=run_id, project_id=project_id,
            )
        else:
            result = self._design_without_llm(
                requirements_json, selected_patterns, research_findings, project_type,
                feedback=feedback,
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
        project_type: str = "traditional",
        feedback: str | None = None,
        run_id: str = "",
        project_id: str = "",
    ) -> dict:
        patterns_text = "\n".join([
            f"- {p.get('name', 'Unknown')}: {p.get('rationale', '')}" for p in selected_patterns
        ]) if selected_patterns else "No specific patterns selected"

        research_text = "\n".join([
            f"- [{f.get('source_type', 'unknown')}] {f.get('claim', '')[:200]}" for f in research_findings[:5]
        ])

        feedback_section = ""
        if feedback:
            feedback_section = f"""

## HUMAN REJECTION FEEDBACK (you MUST address this)
The previous architecture was rejected by the human reviewer with the following feedback:
{feedback}

Revise the architecture to address these concerns. Do NOT repeat the same design."""

        user_message = f"""## Requirements

{requirements_md[:2000]}

## Project Type: {project_type}

## Selected Patterns
{patterns_text}

## Research Findings
{research_text}
{feedback_section}

## Task
Design the system architecture for this {project_type} project. Return JSON with architecture_md and architecture_json fields."""

        try:
            from src.observability.token_callback import TokenTrackingCallback
            callback = TokenTrackingCallback(run_id, project_id, "architect") if run_id and project_id else None
            config = {"callbacks": [callback]} if callback else {}
            response = await self.llm.ainvoke([
                SystemMessage(content=ARCHITECT_SYSTEM_PROMPT),
                HumanMessage(content=user_message),
            ], config=config)

            content = response.content
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]

            return json.loads(content.strip())
        except Exception as e:
            logger.warning("LLM architecture design failed, using fallback: %s", e)
            return self._design_without_llm(requirements_json, selected_patterns, research_findings, project_type, feedback=feedback)

    def _design_without_llm(
        self,
        requirements_json: dict,
        selected_patterns: list[dict],
        research_findings: list[dict],
        project_type: str = "traditional",
        feedback: str | None = None,
    ) -> dict:
        frs = requirements_json.get("functional_requirements", [])
        pattern_names = [p.get("name", "Unknown") for p in selected_patterns]

        architecture_md = "# Architecture Document\n\n"

        if feedback:
            architecture_md += f"## Revision Notes\nIncorporating human feedback: {feedback}\n\n"

        architecture_md += "## Overview\n\n"

        if project_type == "agentic":
            architecture_md += "Agentic system designed to fulfill requirements using AI agent patterns.\n\n"
        else:
            architecture_md += "System designed to fulfill the project requirements using standard architectural patterns.\n\n"

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

        if project_type == "agentic":
            data_flow = [
                {"from": "User", "to": "Agent Router", "data": "Requests", "protocol": "HTTP"},
                {"from": "Agent Router", "to": "Agent Workers", "data": "Tasks", "protocol": "Internal"},
                {"from": "Agent Workers", "to": "Tools & APIs", "data": "Tool calls", "protocol": "Various"},
            ]
            infrastructure = ["LLM API", "Vector Store", "Tool Server", "State Management"]
        else:
            has_microservice = any("microservice" in p.lower() for p in pattern_names)
            has_event = any("event" in p.lower() for p in pattern_names)

            if has_microservice:
                data_flow = [
                    {"from": "Client", "to": "API Gateway", "data": "HTTP Requests", "protocol": "HTTPS"},
                    {"from": "API Gateway", "to": "Service A", "data": "Requests", "protocol": "gRPC"},
                    {"from": "Service A", "to": "Service B", "data": "Events", "protocol": "Message Queue"},
                    {"from": "Services", "to": "Database", "data": "Queries", "protocol": "SQL/NoSQL"},
                ]
                infrastructure = ["API Gateway", "Container Orchestrator", "Message Broker", "Database Cluster"]
            elif has_event:
                data_flow = [
                    {"from": "Producers", "to": "Event Bus", "data": "Events", "protocol": "Async"},
                    {"from": "Event Bus", "to": "Consumers", "data": "Events", "protocol": "Async"},
                    {"from": "Consumers", "to": "Database", "data": "State Updates", "protocol": "SQL"},
                ]
                infrastructure = ["Message Broker", "Event Store", "Database", "Cache"]
            else:
                data_flow = [
                    {"from": "Client", "to": "API Layer", "data": "HTTP Requests", "protocol": "HTTPS"},
                    {"from": "API Layer", "to": "Business Logic", "data": "Commands", "protocol": "Internal"},
                    {"from": "Business Logic", "to": "Data Access", "data": "Queries", "protocol": "Internal"},
                    {"from": "Data Access", "to": "Database", "data": "SQL", "protocol": "TCP"},
                ]
                infrastructure = ["Web Server", "Application Server", "Database", "Cache"]

        architecture_json = {
            "overview": f"System implementing {len(frs)} functional requirements using {len(pattern_names)} patterns",
            "components": components,
            "data_flow": data_flow,
            "patterns_implementation": {p: "Standard implementation" for p in pattern_names},
            "deployment": {
                "considerations": ["Authentication", "Error handling", "Logging", "Monitoring"],
                "infrastructure": infrastructure,
            },
            "risks": [
                {"risk": "Integration complexity", "mitigation": "Incremental implementation"},
                {"risk": "Scalability bottlenecks", "mitigation": "Load testing and monitoring"},
            ],
        }

        return {
            "architecture_md": architecture_md,
            "architecture_json": architecture_json,
        }


architect_agent = ArchitectAgent()
