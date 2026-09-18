import json
import logging
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from src.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

WORKFLOW_REVIEWER_PROMPT = """You are a Workflow Reviewer agent for an AI Agent Factory.

Your role is to validate that generated code correctly implements the selected agentic design patterns.

## Validation Criteria:
1. Agent orchestration matches the selected patterns
2. State management follows pattern requirements
3. Tool integration is correct for the pattern type
4. Error handling aligns with pattern expectations

## Output Format (JSON):
{
  "verdict": "pass|fail",
  "score": 0-100,
  "issues": ["issue1", "issue2"],
  "feedback": "Detailed feedback"
}
"""

PROMPT_REVIEWER_PROMPT = """You are a Prompt Reviewer agent for an AI Agent Factory.

Your role is to validate the quality and safety of prompts used in the generated code.

## Validation Criteria:
1. Prompts are clear and well-structured
2. System prompts have proper role definitions
3. No prompt injection vulnerabilities in dynamic content handling
4. User input is properly sanitized before inclusion in prompts

## Output Format (JSON):
{
  "verdict": "pass|fail",
  "score": 0-100,
  "issues": ["issue1", "issue2"],
  "feedback": "Detailed feedback"
}
"""

SECURITY_REVIEWER_PROMPT = """You are a Security Reviewer agent for an AI Agent Factory.

Your role is to validate security best practices in the generated code.

## Validation Criteria (OWASP basics):
1. Input validation on all external inputs
2. No hardcoded secrets or credentials
3. Proper error handling without information leakage
4. Safe file operations (path traversal prevention)
5. Authentication/authorization checks where needed

## Output Format (JSON):
{
  "verdict": "pass|fail",
  "score": 0-100,
  "issues": ["issue1", "issue2"],
  "feedback": "Detailed feedback"
}
"""


class ReviewerAgents:
    def __init__(self):
        self.llm = None
        if settings.OPENAI_API_KEY:
            self.llm = ChatOpenAI(
                model="gpt-4o",
                api_key=settings.OPENAI_API_KEY,
                temperature=0.2,
            )

    async def review_workflow(self, files: list[dict], patterns: list[dict], task: dict) -> dict:
        return await self._review(
            WORKFLOW_REVIEWER_PROMPT, "workflow_reviewer",
            files, patterns, task,
            "Check that agent orchestration matches selected patterns",
        )

    async def review_prompt(self, files: list[dict], patterns: list[dict], task: dict) -> dict:
        return await self._review(
            PROMPT_REVIEWER_PROMPT, "prompt_reviewer",
            files, patterns, task,
            "Check prompt clarity, role definitions, and injection resistance",
        )

    async def review_security(self, files: list[dict], patterns: list[dict], task: dict) -> dict:
        return await self._review(
            SECURITY_REVIEWER_PROMPT, "security_reviewer",
            files, patterns, task,
            "Check OWASP basics: input validation, secrets, error handling",
        )

    async def _review(
        self,
        system_prompt: str,
        reviewer_name: str,
        files: list[dict],
        patterns: list[dict],
        task: dict,
        focus: str,
    ) -> dict:
        if self.llm:
            return await self._review_with_llm(
                system_prompt, files, patterns, task, focus,
            )
        return self._review_without_llm(files, task, reviewer_name)

    async def _review_with_llm(
        self,
        system_prompt: str,
        files: list[dict],
        patterns: list[dict],
        task: dict,
        focus: str,
    ) -> dict:
        files_text = "\n\n".join([
            f"### {f['path']}\n```python\n{f['content'][:2000]}\n```"
            for f in files
        ])

        patterns_text = "\n".join([
            f"- {p.get('name', 'Unknown')}: {p.get('rationale', '')}"
            for p in patterns
        ])

        user_message = f"""## Generated Code
{files_text}

## Task
Title: {task.get('title', '')}
Description: {task.get('description', '')}

## Selected Patterns
{patterns_text}

## Review Focus
{focus}

Return JSON with verdict, score, issues, and feedback."""

        try:
            response = await self.llm.ainvoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_message),
            ])

            content = response.content
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]

            result = json.loads(content.strip())
            result.setdefault("verdict", "pass")
            result.setdefault("score", 80)
            result.setdefault("issues", [])
            result.setdefault("feedback", "")
            return result
        except Exception as e:
            logger.warning("LLM review failed for %s: %s", focus, e)
            return self._review_without_llm(files, task, focus)

    def _review_without_llm(
        self,
        files: list[dict],
        task: dict,
        reviewer_name: str,
    ) -> dict:
        issues = []
        score = 100

        for f in files:
            content = f.get("content", "")
            path = f.get("path", "")

            if not content.strip():
                issues.append(f"{path}: Empty file")
                score -= 20

            if "TODO" in content or "FIXME" in content:
                issues.append(f"{path}: Contains TODO/FIXME markers")
                score -= 5

            if reviewer_name == "security_reviewer":
                if "password" in content.lower() and "=" in content:
                    issues.append(f"{path}: Possible hardcoded credential")
                    score -= 15
                if "eval(" in content or "exec(" in content:
                    issues.append(f"{path}: Uses eval/exec (potential security risk)")
                    score -= 10

            if reviewer_name == "prompt_reviewer":
                if "system_message" in content.lower() and "{{" in content:
                    issues.append(f"{path}: Unescaped template syntax in prompt")
                    score -= 10

        if not files:
            issues.append("No files generated for review")
            score = 0

        return {
            "verdict": "pass" if score >= 60 else "fail",
            "score": max(0, score),
            "issues": issues,
            "feedback": f"{reviewer_name} review: {len(issues)} issues found" if issues else f"{reviewer_name} review: All checks passed",
        }


reviewer_agents = ReviewerAgents()
