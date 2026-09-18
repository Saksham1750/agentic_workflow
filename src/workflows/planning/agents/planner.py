import json
import logging
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from src.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

PLANNER_SYSTEM_PROMPT = """You are a Planner agent for an AI Agent Factory.

Your role is to decompose the architecture into an ordered, code-ready task list.

## Instructions:
1. Break down the architecture into implementable tasks
2. Each task must be atomic (can be completed independently)
3. Order tasks by dependencies (no forward dependencies)
4. Include acceptance criteria for each task
5. Reference which patterns inform each task's implementation

## Task Requirements:
- Title: Clear, descriptive name
- Description: What needs to be implemented
- Target files: Files to create or modify
- Acceptance criteria: How to verify completion
- Dependencies: Task IDs that must complete first
- Pattern references: Which patterns guide implementation

## Output Format (JSON):
{
  "tasks": [
    {
      "task_id": "task_001",
      "title": "Task title",
      "description": "Detailed description",
      "target_files": ["src/path/to/file.py"],
      "acceptance_criteria": ["criteria1", "criteria2"],
      "dependencies": [],
      "pattern_refs": ["Pattern Name"],
      "estimated_complexity": "low|medium|high"
    }
  ],
  "ordering_rationale": "Why tasks are ordered this way"
}
"""


class PlannerAgent:
    def __init__(self):
        self.llm = None
        if settings.OPENAI_API_KEY:
            self.llm = ChatOpenAI(
                model="gpt-4o",
                api_key=settings.OPENAI_API_KEY,
                temperature=0.3,
            )

    async def create_task_plan(self, state: dict) -> dict:
        requirements_json = state.get("requirements_json", {})
        architecture_json = state.get("architecture_json", {})
        selected_patterns = state.get("selected_patterns", [])

        if self.llm:
            result = await self._plan_with_llm(
                requirements_json, architecture_json, selected_patterns
            )
        else:
            result = self._plan_without_llm(
                requirements_json, architecture_json, selected_patterns
            )

        return {
            "tasks": result["tasks"],
            "current_phase": "tasks_planned",
        }

    async def _plan_with_llm(
        self,
        requirements_json: dict,
        architecture_json: dict,
        selected_patterns: list[dict],
    ) -> dict:
        user_message = f"""## Requirements
{json.dumps(requirements_json, indent=2)[:2000]}

## Architecture
{json.dumps(architecture_json, indent=2)[:2000]}

## Selected Patterns
{json.dumps(selected_patterns, indent=2)[:1000]}

## Task
Create an ordered task list. Return JSON with tasks array."""

        try:
            response = await self.llm.ainvoke([
                SystemMessage(content=PLANNER_SYSTEM_PROMPT),
                HumanMessage(content=user_message),
            ])

            content = response.content
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]

            return json.loads(content.strip())
        except Exception as e:
            logger.warning("LLM planning failed, using fallback: %s", e)
            return self._plan_without_llm(requirements_json, architecture_json, selected_patterns)

    def _plan_without_llm(
        self,
        requirements_json: dict,
        architecture_json: dict,
        selected_patterns: list[dict],
    ) -> dict:
        frs = requirements_json.get("functional_requirements", [])
        components = architecture_json.get("components", [])
        pattern_names = [p.get("name", "Unknown") for p in selected_patterns]

        tasks = []
        task_id = 1

        tasks.append({
            "task_id": f"task_{task_id:03d}",
            "title": "Project Setup and Configuration",
            "description": "Initialize project structure, dependencies, and configuration",
            "target_files": ["pyproject.toml", "src/config.py", ".env"],
            "acceptance_criteria": [
                "Project structure created",
                "Dependencies installed",
                "Configuration loaded from environment"
            ],
            "dependencies": [],
            "pattern_refs": [],
            "estimated_complexity": "low",
        })
        task_id += 1

        tasks.append({
            "task_id": f"task_{task_id:03d}",
            "title": "Database Models and Schema",
            "description": "Define SQLAlchemy models and database schema",
            "target_files": ["src/models/", "src/database.py"],
            "acceptance_criteria": [
                "Models defined",
                "Database initialization works",
                "Tables created successfully"
            ],
            "dependencies": ["task_001"],
            "pattern_refs": [],
            "estimated_complexity": "low",
        })
        task_id += 1

        for fr in frs[:10]:
            comp_name = fr.get("title", "Feature").replace(" ", "")
            tasks.append({
                "task_id": f"task_{task_id:03d}",
                "title": f"Implement {fr.get('title', 'Feature')}",
                "description": fr.get("content", "")[:500],
                "target_files": [f"src/services/{comp_name.lower()}.py"],
                "acceptance_criteria": [
                    f"Functionality for {fr.get('title', '')} implemented",
                    "Unit tests passing",
                ],
                "dependencies": ["task_002"],
                "pattern_refs": pattern_names[:2],
                "estimated_complexity": "medium",
            })
            task_id += 1

        tasks.append({
            "task_id": f"task_{task_id:03d}",
            "title": "API Endpoints",
            "description": "Implement REST API endpoints for all features",
            "target_files": ["src/routers/"],
            "acceptance_criteria": [
                "All endpoints implemented",
                "Input validation working",
                "Error handling in place"
            ],
            "dependencies": [f"task_{task_id - len(frs[:10]) - 1:03d}"],
            "pattern_refs": pattern_names[:1],
            "estimated_complexity": "medium",
        })
        task_id += 1

        tasks.append({
            "task_id": f"task_{task_id:03d}",
            "title": "Integration Testing",
            "description": "Write integration tests for all workflows",
            "target_files": ["tests/integration/"],
            "acceptance_criteria": [
                "Integration tests passing",
                "End-to-end flow verified",
                "Edge cases covered"
            ],
            "dependencies": [f"task_{task_id - 1:03d}"],
            "pattern_refs": [],
            "estimated_complexity": "medium",
        })

        return {
            "tasks": tasks,
            "ordering_rationale": "Tasks ordered by dependency: setup -> models -> features -> API -> tests",
        }


planner_agent = PlannerAgent()
