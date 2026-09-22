import json
import logging
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq

from src.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

DEVELOPER_SYSTEM_PROMPT = """You are a Senior Developer agent for an AI Agent Factory.

Your role is to generate PRODUCTION-READY, RUNNABLE Python code for a given task. The code must work as-is when the user runs it.

## CRITICAL RULES:
1. Every file must be COMPLETE and SELF-CONTAINED with all imports
2. Use ONLY standard library + the dependencies listed in the requirements context
3. All imports must reference packages that will be in requirements.txt
4. Include proper error handling, type hints, docstrings, and logging
5. If pattern references are provided, follow their structure and prerequisites. If pattern references are empty or 'None', generate standard implementation code without agent abstractions.
6. DO NOT generate placeholder/stub code — write REAL implementations
7. Each file must be syntactically valid Python

## For each file, generate:
- Complete module docstring explaining purpose
- All necessary imports at the top
- Full class/function implementations with real logic
- Error handling with proper exceptions
- Type hints on all function signatures
- Logging where appropriate

## Output Format (JSON):
{
  "files": [
    {
      "path": "src/package/module.py",
      "content": "The complete, runnable file content with ALL imports",
      "action": "create"
    }
  ],
  "summary": "Brief summary of what was generated",
  "notes": "Implementation decisions and design rationale"
}
"""

IMPORT_MAP = {
    "fastapi": "fastapi",
    "uvicorn": "uvicorn[standard]",
    "sqlalchemy": "sqlalchemy[asyncio]",
    "aiosqlite": "aiosqlite",
    "pydantic": "pydantic",
    "pydantic_settings": "pydantic-settings",
    "langchain": "langchain",
    "langchain_core": "langchain-core",
    "langchain_openai": "langchain-openai",
    "langgraph": "langgraph",
    "chromadb": "chromadb",
    "httpx": "httpx",
    "aiofiles": "aiofiles",
    "jwt": "python-jose[cryptography]",
    "passlib": "passlib[bcrypt]",
    "multipart": "python-multipart",
    "yaml": "pyyaml",
    "markdown": "markdown",
    "pypdf": "pypdf",
    "docx": "python-docx",
    "pptx": "python-pptx",
    "openpyxl": "openpyxl",
}


class DeveloperAgent:
    def __init__(self):
        self.llm = None
        if settings.GROQ_API_KEY:
            self.llm = ChatGroq(
                model=settings.LLM_MODEL,
                api_key=settings.GROQ_API_KEY,
                temperature=0.3,
                timeout=60,
                max_retries=2,
            )

    async def generate_code(self, state: dict) -> dict:
        tasks = state.get("tasks", [])
        current_index = state.get("current_task_index", 0)

        if current_index >= len(tasks):
            return {"files": [], "summary": "No more tasks to process"}

        current_task = tasks[current_index]
        requirements_md = state.get("requirements_md") or ""
        architecture_json = state.get("architecture_json") or {}
        selected_patterns = state.get("selected_patterns") or []
        review_feedback = state.get("review_feedback")
        human_feedback = state.get("feedback")
        existing_files = state.get("workspace_files") or []

        run_id = state.get("run_id", "")
        project_id = state.get("project_id", "")

        if self.llm:
            result = await self._generate_with_llm(
                current_task, requirements_md, architecture_json,
                selected_patterns, review_feedback, existing_files,
                human_feedback=human_feedback, run_id=run_id, project_id=project_id,
            )
        else:
            result = self._generate_without_llm(
                current_task, requirements_md, architecture_json,
                selected_patterns, review_feedback, existing_files,
                human_feedback=human_feedback,
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
        human_feedback: str | None = None,
        run_id: str = "",
        project_id: str = "",
    ) -> dict:
        patterns_section = ""
        if selected_patterns:
            patterns_text = "\n".join([
                f"- {p.get('name', 'Unknown')}: {p.get('rationale', '')}"
                for p in selected_patterns
            ])
            patterns_section = f"\n## SELECTED PATTERNS\n{patterns_text}\n"

        existing_files_section = ""
        if existing_files:
            existing_files_section = "\n## ALREADY GENERATED FILES (for cross-file imports and context)\n"
            existing_files_section += "You MUST import from these files if your task depends on them.\n"
            for ef in existing_files:
                existing_files_section += f"\n### {ef['path']}\n```python\n{ef['content'][:1500]}\n```\n"

        feedback_context = ""
        if review_feedback:
            feedback_context = f"\n## REVIEW FEEDBACK (you MUST fix these issues)\n{review_feedback}\n"

        human_feedback_context = ""
        if human_feedback:
            human_feedback_context = f"\n## HUMAN REJECTION FEEDBACK (you MUST address this)\nThe previous code was rejected by the human reviewer with the following feedback:\n{human_feedback}\nRevise the implementation to address these concerns.\n"

        user_message = f"""## CURRENT TASK
Title: {task.get('title', '')}
Description: {task.get('description', '')}
Target Files: {', '.join(task.get('target_files', []))}
Acceptance Criteria: {json.dumps(task.get('acceptance_criteria', []))}
Dependencies (must complete first): {json.dumps(task.get('dependencies', []))}
Pattern References: {json.dumps(task.get('pattern_refs', [])) if task.get('pattern_refs') else 'None — generate standard implementation code'}
{patterns_section}
## ARCHITECTURE
{json.dumps(architecture_json, indent=2)[:3000]}

## REQUIREMENTS
{requirements_md[:3000]}
{existing_files_section}
{feedback_context}
{human_feedback_context}

## INSTRUCTIONS
Generate COMPLETE, RUNNABLE Python code for this task. Every file must:
1. Have ALL imports at the top (including imports from files listed above)
2. Be syntactically valid Python
3. Contain real implementation logic, not stubs or placeholders
4. Include type hints, docstrings, and error handling

Return JSON with the files array."""

        try:
            from src.observability.token_callback import TokenTrackingCallback
            callback = TokenTrackingCallback(run_id, project_id, "developer") if run_id and project_id else None
            config = {"callbacks": [callback]} if callback else {}
            response = await self.llm.ainvoke([
                SystemMessage(content=DEVELOPER_SYSTEM_PROMPT),
                HumanMessage(content=user_message),
            ], config=config)

            content = response.content
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]

            result = json.loads(content.strip())
            logger.info("LLM generated %d files for task %s", len(result.get("files", [])), task.get("task_id"))
            return result
        except Exception as e:
            logger.warning("LLM code generation failed, using fallback: %s", e)
            return self._generate_without_llm(
                task, requirements_md, architecture_json,
                selected_patterns, review_feedback, existing_files,
                human_feedback=human_feedback,
            )

    def _generate_without_llm(
        self,
        task: dict,
        requirements_md: str,
        architecture_json: dict,
        selected_patterns: list[dict],
        review_feedback: str | None,
        existing_files: list[dict],
        human_feedback: str | None = None,
    ) -> dict:
        title = task.get("title", "Untitled Task")
        description = task.get("description", "")
        target_files = task.get("target_files", [])
        task_id = task.get("task_id", "unknown")
        acceptance = task.get("acceptance_criteria", [])
        pattern_refs = task.get("pattern_refs", [])

        files = []
        for file_path in target_files:
            if file_path.endswith(".py"):
                module_name = file_path.replace("/", ".").replace("\\", ".").replace(".py", "")
                parts = module_name.split(".")
                class_name = "".join(part.capitalize() for part in parts[-1].split("_"))

                imports = "import logging\nfrom typing import Any\n"
                for ef in existing_files:
                    ef_path = ef.get("path", "")
                    if ef_path.endswith(".py") and ef_path != file_path:
                        ef_module = ef_path.replace("/", ".").replace("\\", ".").replace(".py", "")
                        ef_class = "".join(p.capitalize() for p in ef_module.split(".")[-1].split("_"))
                        imports += f"from {ef_module} import {ef_class}\n"

                content = f'"""{title}\n\n{description[:800]}\n\nAcceptance Criteria:\n'
                for ac in acceptance:
                    content += f"- {ac}\n"
                content += '"""\n\n'
                content += imports + "\n"
                content += f"logger = logging.getLogger(__name__)\n\n\n"
                content += f"class {class_name}:\n"
                content += f'    """\n    {title}\n\n    Handles: {description[:200]}\n    """\n\n'
                content += "    def __init__(self, config: dict[str, Any] | None = None):\n"
                content += '        """Initialize the component.\n\n        Args:\n            config: Optional configuration dictionary.\n        """\n'
                content += "        self.config = config or {}\n"
                content += "        self.logger = logging.getLogger(self.__class__.__name__)\n"
                content += "        self._initialized = False\n\n"
                content += "    async def initialize(self) -> None:\n"
                content += '        """Perform async initialization."""\n'
                content += "        self.logger.info('Initializing %s', self.__class__.__name__)\n"
                content += "        self._initialized = True\n\n"
                content += "    async def execute(self, **kwargs) -> dict[str, Any]:\n"
                content += '        """Execute the main logic.\n\n        Args:\n            **kwargs: Runtime parameters.\n\n        Returns:\n            Dictionary with execution results.\n\n        Raises:\n            RuntimeError: If not initialized.\n            ValueError: If required parameters are missing.\n        """\n'
                content += "        if not self._initialized:\n"
                content += "            await self.initialize()\n\n"
                content += "        self.logger.info('Executing %s', self.__class__.__name__)\n\n"
                content += "        try:\n"
                content += "            result = await self._process(**kwargs)\n"
                content += "            self.logger.info('Completed %s successfully', self.__class__.__name__)\n"
                content += f"            return {{'status': 'completed', 'task_id': '{task_id}', 'result': result}}\n"
                content += "        except Exception as e:\n"
                content += "            self.logger.error('Failed: %s', str(e))\n"
                content += f"            return {{'status': 'failed', 'task_id': '{task_id}', 'error': str(e)}}\n\n"
                content += "    async def _process(self, **kwargs) -> dict[str, Any]:\n"
                content += '        """Core processing logic. Override in subclasses."""\n'
                content += f"        return {{'message': 'Implementation pending', 'component': '{class_name}'}}\n"

                files.append({
                    "path": file_path,
                    "content": content,
                    "action": "create",
                })

        if not files:
            safe_title = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in title.lower().replace(" ", "_"))
            file_path = f"src/{safe_title}.py"
            content = f'"""{title}\n\n{description[:800]}\n\nAcceptance Criteria:\n'
            for ac in acceptance:
                content += f"- {ac}\n"
            content += '"""\n\n'
            content += "import logging\nfrom typing import Any\n\n\n"
            content += f"logger = logging.getLogger(__name__)\n\n\n"
            content += f"async def run(config: dict[str, Any] | None = None) -> dict[str, Any]:\n"
            content += f'    """\n    {title}\n\n    {description[:200]}\n\n    Args:\n        config: Optional configuration.\n\n    Returns:\n        Execution result dictionary.\n    """\n'
            content += "    config = config or {}\n"
            content += f"    logger.info('Running {title}')\n\n"
            content += "    try:\n"
            content += f"        result = {{'status': 'completed', 'task_id': '{task_id}'}}\n"
            content += f"        logger.info('Completed {title}')\n"
            content += "        return result\n"
            content += "    except Exception as e:\n"
            content += "        logger.error('Failed: %s', str(e))\n"
            content += "        return {'status': 'failed', 'error': str(e)}\n"

            files.append({
                "path": file_path,
                "content": content,
                "action": "create",
            })

        logger.info("Fallback generated %d files for task %s", len(files), task_id)

        return {
            "files": files,
            "summary": f"Generated {len(files)} files for task: {title}",
            "notes": f"Task {task_id} implementation" + (" with review feedback incorporated" if review_feedback else ""),
        }


developer_agent = DeveloperAgent()
