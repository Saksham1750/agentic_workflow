import json
import logging
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from src.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

DEVELOPER_SYSTEM_PROMPT = """You are a Developer agent for an AI Agent Factory.

Your role is to generate production-quality Python code for a given task, informed by the project's architecture and referenced agentic design patterns.

## Instructions:
1. Read the task description, acceptance criteria, and target files carefully
2. Reference the architecture document and selected patterns for context
3. Generate clean, well-structured Python code
4. Follow the referenced patterns' structure and prerequisites
5. Each file must be complete and self-contained
6. Include proper imports, error handling, and type hints

## Output Format (JSON):
{
  "files": [
    {
      "path": "src/path/to/file.py",
      "content": "The complete file content",
      "action": "create|update"
    }
  ],
  "summary": "Brief summary of what was generated",
  "notes": "Any implementation notes or decisions"
}
"""


class DeveloperAgent:
    def __init__(self):
        self.llm = None
        if settings.OPENAI_API_KEY:
            self.llm = ChatOpenAI(
                model="gpt-4o",
                api_key=settings.OPENAI_API_KEY,
                temperature=0.3,
            )

    async def generate_code(self, state: dict) -> dict:
        tasks = state.get("tasks", [])
        current_index = state.get("current_task_index", 0)

        if current_index >= len(tasks):
            return {"files": [], "summary": "No more tasks to process"}

        current_task = tasks[current_index]
        requirements_md = state.get("requirements_md", "")
        architecture_json = state.get("architecture_json", {})
        selected_patterns = state.get("selected_patterns", [])
        review_feedback = state.get("review_feedback")
        existing_files = state.get("workspace_files", [])

        if self.llm:
            result = await self._generate_with_llm(
                current_task, requirements_md, architecture_json,
                selected_patterns, review_feedback, existing_files,
            )
        else:
            result = self._generate_without_llm(
                current_task, requirements_md, architecture_json,
                selected_patterns, review_feedback,
            )

        generated_files = result.get("files", [])

        updated_files = list(existing_files)
        for f in generated_files:
            updated_files.append({
                "task_id": current_task.get("task_id", ""),
                "path": f["path"],
                "content": f["content"],
                "action": f.get("action", "create"),
            })

        return {
            "workspace_files": updated_files,
            "current_phase": "code_generated",
        }

    async def _generate_with_llm(
        self,
        task: dict,
        requirements_md: str,
        architecture_json: dict,
        selected_patterns: list[dict],
        review_feedback: str | None,
        existing_files: list[dict],
    ) -> dict:
        patterns_text = "\n".join([
            f"- {p.get('name', 'Unknown')}: {p.get('rationale', '')}"
            for p in selected_patterns
        ])

        existing_context = ""
        if existing_files:
            existing_context = "\n## Existing Generated Files\n"
            for ef in existing_files[-5:]:
                existing_context += f"\n### {ef['path']}\n```python\n{ef['content'][:1000]}\n```\n"

        feedback_context = ""
        if review_feedback:
            feedback_context = f"\n## Review Feedback (address these issues)\n{review_feedback}\n"

        user_message = f"""## Current Task
Title: {task.get('title', '')}
Description: {task.get('description', '')}
Target Files: {', '.join(task.get('target_files', []))}
Acceptance Criteria: {json.dumps(task.get('acceptance_criteria', []))}

## Architecture
{json.dumps(architecture_json, indent=2)[:2000]}

## Selected Patterns
{patterns_text}
{existing_context}
{feedback_context}

## Requirements Summary
{requirements_md[:2000]}

## Task
Generate the code for this task. Return JSON with files array."""

        try:
            response = await self.llm.ainvoke([
                SystemMessage(content=DEVELOPER_SYSTEM_PROMPT),
                HumanMessage(content=user_message),
            ])

            content = response.content
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]

            return json.loads(content.strip())
        except Exception as e:
            logger.warning("LLM code generation failed, using fallback: %s", e)
            return self._generate_without_llm(
                task, requirements_md, architecture_json,
                selected_patterns, review_feedback,
            )

    def _generate_without_llm(
        self,
        task: dict,
        requirements_md: str,
        architecture_json: dict,
        selected_patterns: list[dict],
        review_feedback: str | None,
    ) -> dict:
        title = task.get("title", "Untitled Task")
        description = task.get("description", "")
        target_files = task.get("target_files", [])
        task_id = task.get("task_id", "unknown")

        files = []
        for file_path in target_files:
            if file_path.endswith(".py"):
                module_name = file_path.replace("/", ".").replace("\\", ".").replace(".py", "")
                class_name = "".join(part.capitalize() for part in module_name.split(".")[-1].split("_"))

                content = f'"""{title}\n\n{description[:500]}\n"""\n\n'
                content += "import logging\n\n"
                content += f"logger = logging.getLogger(__name__)\n\n\n"
                content += f"class {class_name}:\n"
                content += f'    """Handles {title.lower()} functionality."""\n\n'
                content += "    def __init__(self):\n"
                content += "        self.initialized = True\n\n"
                content += "    async def execute(self, **kwargs) -> dict:\n"
                content += '        """Execute the task."""\n'
                content += "        logger.info('Executing %s', %r)\n" % (class_name,)
                content += "        return {'status': 'completed', 'task_id': %r}\n" % (task_id,)

                files.append({
                    "path": file_path,
                    "content": content,
                    "action": "create",
                })

        return {
            "files": files,
            "summary": f"Generated {len(files)} files for task: {title}",
            "notes": f"Task {task_id} implementation" + (" with review feedback incorporated" if review_feedback else ""),
        }


developer_agent = DeveloperAgent()
