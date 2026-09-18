import json
import logging
from pathlib import Path

from src.config import get_settings
from src.storage.file_store import file_store

logger = logging.getLogger(__name__)
settings = get_settings()


class ArtifactService:
    def _runs_dir(self, project_id: str, run_id: str) -> str:
        return str(Path(settings.DATA_ROOT) / "projects" / project_id / "runs" / run_id)

    async def save_requirements(
        self,
        project_id: str,
        run_id: str,
        requirements_md: str,
        requirements_json: dict,
    ):
        runs_dir = self._runs_dir(project_id, run_id)
        await file_store.write_text(f"{runs_dir}/requirements.md", requirements_md)
        await file_store.write_text(
            f"{runs_dir}/requirements.json",
            json.dumps(requirements_json, indent=2),
        )
        logger.info("Saved requirements artifacts for run %s", run_id)

    async def save_requirements_preview(
        self,
        project_id: str,
        run_id: str,
        requirements_md: str,
    ):
        runs_dir = self._runs_dir(project_id, run_id)
        await file_store.write_text(f"{runs_dir}/requirements_preview.md", requirements_md)

    async def load_requirements(
        self,
        project_id: str,
        run_id: str,
    ) -> tuple[str | None, dict | None]:
        runs_dir = self._runs_dir(project_id, run_id)
        md_path = f"{runs_dir}/requirements.md"
        json_path = f"{runs_dir}/requirements.json"

        requirements_md = None
        requirements_json = None

        if await file_store.file_exists(md_path):
            content = await file_store.read_file(md_path)
            requirements_md = content.decode("utf-8")

        if await file_store.file_exists(json_path):
            content = await file_store.read_file(json_path)
            requirements_json = json.loads(content.decode("utf-8"))

        return requirements_md, requirements_json

    async def save_pattern_report(
        self,
        project_id: str,
        run_id: str,
        patterns: list[dict],
    ):
        runs_dir = self._runs_dir(project_id, run_id)
        await file_store.write_text(
            f"{runs_dir}/patterns_report.json",
            json.dumps(patterns, indent=2),
        )

    async def save_planning_artifacts(
        self,
        project_id: str,
        run_id: str,
        selected_patterns: list[dict],
        research_findings: list[dict],
        architecture_md: str,
        architecture_json: dict,
        tasks: list[dict],
        task_validation: dict,
    ):
        runs_dir = self._runs_dir(project_id, run_id)

        await file_store.write_text(
            f"{runs_dir}/selected_patterns.json",
            json.dumps(selected_patterns, indent=2),
        )

        await file_store.write_text(
            f"{runs_dir}/research_findings.json",
            json.dumps(research_findings, indent=2),
        )

        await file_store.write_text(f"{runs_dir}/architecture.md", architecture_md)
        await file_store.write_text(
            f"{runs_dir}/architecture.json",
            json.dumps(architecture_json, indent=2),
        )

        await file_store.write_text(
            f"{runs_dir}/task_plan.json",
            json.dumps(tasks, indent=2),
        )

        await file_store.write_text(
            f"{runs_dir}/task_validation.json",
            json.dumps(task_validation, indent=2),
        )

        logger.info("Saved planning artifacts for run %s", run_id)

    async def load_planning_state(
        self,
        project_id: str,
        run_id: str,
    ) -> dict:
        runs_dir = self._runs_dir(project_id, run_id)

        state = {}

        json_path = f"{runs_dir}/selected_patterns.json"
        if await file_store.file_exists(json_path):
            content = await file_store.read_file(json_path)
            state["selected_patterns"] = json.loads(content.decode("utf-8"))

        json_path = f"{runs_dir}/architecture.json"
        if await file_store.file_exists(json_path):
            content = await file_store.read_file(json_path)
            state["architecture_json"] = json.loads(content.decode("utf-8"))

        json_path = f"{runs_dir}/task_plan.json"
        if await file_store.file_exists(json_path):
            content = await file_store.read_file(json_path)
            state["tasks"] = json.loads(content.decode("utf-8"))

        return state

    async def list_artifacts(self, project_id: str, run_id: str) -> list[dict]:
        runs_dir = Path(self._runs_dir(project_id, run_id))
        if not runs_dir.exists():
            return []
        artifacts = []
        for f in sorted(runs_dir.iterdir()):
            if f.is_file():
                artifacts.append({
                    "filename": f.name,
                    "size": f.stat().st_size,
                })
        return artifacts


artifact_service = ArtifactService()
