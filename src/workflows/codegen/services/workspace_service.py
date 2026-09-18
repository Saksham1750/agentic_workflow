import json
import logging
from pathlib import Path

from src.config import get_settings
from src.storage.file_store import file_store

logger = logging.getLogger(__name__)
settings = get_settings()


class WorkspaceService:
    def _workspace_dir(self, project_id: str, run_id: str) -> str:
        return str(Path(settings.DATA_ROOT) / "projects" / project_id / "runs" / run_id / "workspace")

    async def write_files(
        self,
        project_id: str,
        run_id: str,
        files: list[dict],
    ) -> list[dict]:
        workspace_dir = self._workspace_dir(project_id, run_id)
        written = []

        for f in files:
            file_path = f"{workspace_dir}/{f['path']}"
            content = f.get("content", "")

            if isinstance(content, str):
                content_bytes = content.encode("utf-8")
            else:
                content_bytes = content

            await file_store.write_file(file_path, content_bytes)
            written.append({
                "path": f["path"],
                "size": len(content_bytes),
                "action": f.get("action", "create"),
            })

            logger.info("Wrote workspace file: %s", f["path"])

        return written

    async def read_file(
        self,
        project_id: str,
        run_id: str,
        file_path: str,
    ) -> bytes | None:
        full_path = f"{self._workspace_dir(project_id, run_id)}/{file_path}"
        if await file_store.file_exists(full_path):
            return await file_store.read_file(full_path)
        return None

    async def list_files(self, project_id: str, run_id: str) -> list[dict]:
        workspace_dir = Path(self._workspace_dir(project_id, run_id))
        if not workspace_dir.exists():
            return []

        files = []
        for f in sorted(workspace_dir.rglob("*")):
            if f.is_file():
                files.append({
                    "path": str(f.relative_to(workspace_dir)),
                    "size": f.stat().st_size,
                })
        return files

    async def create_bundle(
        self,
        project_id: str,
        run_id: str,
        task_file_map: dict[str, list[str]] | None = None,
    ) -> str:
        import zipfile

        workspace_dir = self._workspace_dir(project_id, run_id)
        runs_dir = str(Path(settings.DATA_ROOT) / "projects" / project_id / "runs" / run_id)
        bundle_path = f"{runs_dir}/bundle.zip"

        manifest = {
            "version": "1.0",
            "run_id": run_id,
            "project_id": project_id,
            "task_files": task_file_map or {},
            "files": [],
        }

        with zipfile.ZipFile(bundle_path, "w", zipfile.ZIP_DEFLATED) as zf:
            workspace = Path(workspace_dir)
            if workspace.exists():
                for f in sorted(workspace.rglob("*")):
                    if f.is_file():
                        arcname = str(f.relative_to(workspace))
                        zf.write(str(f), arcname)
                        manifest["files"].append({
                            "path": arcname,
                            "size": f.stat().st_size,
                        })

            manifest_json = json.dumps(manifest, indent=2)
            zf.writestr("MANIFEST.json", manifest_json)

        logger.info("Created bundle at %s with %d files", bundle_path, len(manifest["files"]))
        return bundle_path


workspace_service = WorkspaceService()
