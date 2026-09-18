import json
import logging
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from src.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

CRITIC_SYSTEM_PROMPT = """You are a Critic/Validator agent for an AI Agent Factory.

Your role is to validate the task plan against requirements and quality criteria.

## Validation Criteria:
1. **Coverage**: Every requirement maps to at least one task
2. **Ordering**: No task depends on a task that comes after it
3. **Pattern Fidelity**: Selected patterns are reflected in task descriptions
4. **Atomicity**: Each task is implementable independently

## Output Format (JSON):
{
  "valid": true|false,
  "score": 0-100,
  "coverage": {
    "covered_requirements": ["FR-001"],
    "uncovered_requirements": ["FR-002"]
  },
  "ordering_issues": [],
  "pattern_issues": [],
  "atomicity_issues": [],
  "feedback": "Overall feedback",
  "suggestions": ["suggestion1"]
}
"""


class CriticAgent:
    def __init__(self):
        self.llm = None
        if settings.OPENAI_API_KEY:
            self.llm = ChatOpenAI(
                model="gpt-4o",
                api_key=settings.OPENAI_API_KEY,
                temperature=0.2,
            )

    async def validate_plan(self, state: dict) -> dict:
        tasks = state.get("tasks", [])
        requirements_json = state.get("requirements_json", {})
        selected_patterns = state.get("selected_patterns", [])

        if self.llm:
            result = await self._validate_with_llm(tasks, requirements_json, selected_patterns)
        else:
            result = self._validate_without_llm(tasks, requirements_json, selected_patterns)

        return {
            "task_validation": result,
            "current_phase": "validation_complete",
        }

    async def _validate_with_llm(
        self,
        tasks: list[dict],
        requirements_json: dict,
        selected_patterns: list[dict],
    ) -> dict:
        user_message = f"""## Task Plan
{json.dumps(tasks, indent=2)[:3000]}

## Requirements
{json.dumps(requirements_json, indent=2)[:2000]}

## Selected Patterns
{json.dumps(selected_patterns, indent=2)[:1000]}

## Task
Validate this plan. Return JSON with validation results."""

        try:
            response = await self.llm.ainvoke([
                SystemMessage(content=CRITIC_SYSTEM_PROMPT),
                HumanMessage(content=user_message),
            ])

            content = response.content
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]

            return json.loads(content.strip())
        except Exception as e:
            logger.warning("LLM validation failed, using rule-based validation: %s", e)
            return self._validate_without_llm(tasks, requirements_json, selected_patterns)

    def _validate_without_llm(
        self,
        tasks: list[dict],
        requirements_json: dict,
        selected_patterns: list[dict],
    ) -> dict:
        frs = requirements_json.get("functional_requirements", [])
        pattern_names = [p.get("name", "") for p in selected_patterns]

        covered = []
        uncovered = []
        for fr in frs:
            fr_id = fr.get("id", "")
            found = any(fr_id in str(t.get("acceptance_criteria", [])) for t in tasks)
            if found:
                covered.append(fr_id)
            else:
                uncovered.append(fr_id)

        coverage_score = len(covered) / len(frs) * 100 if frs else 100

        ordering_issues = []
        task_ids = [t.get("task_id", "") for t in tasks]
        for task in tasks:
            deps = task.get("dependencies", [])
            task_idx = task_ids.index(task.get("task_id", "")) if task.get("task_id") in task_ids else -1
            for dep in deps:
                dep_idx = task_ids.index(dep) if dep in task_ids else -1
                if dep_idx > task_idx:
                    ordering_issues.append(f"Task {task.get('task_id')} depends on {dep} which comes after it")

        pattern_issues = []
        tasks_with_patterns = [t for t in tasks if t.get("pattern_refs")]
        if selected_patterns and not tasks_with_patterns:
            pattern_issues.append("No tasks reference any selected patterns")

        atomicity_issues = []
        for task in tasks:
            desc = task.get("description", "")
            if len(desc) > 1000:
                atomicity_issues.append(f"Task {task.get('task_id')} may be too complex")

        all_issues = len(ordering_issues) + len(pattern_issues) + len(atomicity_issues)
        score = max(0, 100 - (all_issues * 10) - (len(uncovered) * 5))

        return {
            "valid": len(ordering_issues) == 0 and len(uncovered) <= 1,
            "score": score,
            "coverage": {
                "covered_requirements": covered,
                "uncovered_requirements": uncovered,
            },
            "ordering_issues": ordering_issues,
            "pattern_issues": pattern_issues,
            "atomicity_issues": atomicity_issues,
            "feedback": f"Coverage: {len(covered)}/{len(frs)} requirements. Score: {score}/100",
            "suggestions": [
                "Ensure all requirements have corresponding tasks" if uncovered else None,
                "Verify task ordering respects dependencies" if ordering_issues else None,
            ],
        }


critic_agent = CriticAgent()
