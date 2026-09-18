import hashlib
from pathlib import Path

import aiofiles
import aiofiles.os

from src.config import get_settings

settings = get_settings()


class FileStore:
    def __init__(self, data_root: str | None = None):
        self.root = Path(data_root or settings.DATA_ROOT)

    def _project_dir(self, project_id: str) -> Path:
        return self.root / "projects" / project_id

    def _upload_dir(self, project_id: str) -> Path:
        return self._project_dir(project_id) / "uploads"

    def _runs_dir(self, project_id: str, run_id: str) -> Path:
        return self._project_dir(project_id) / "runs" / run_id

    async def save_upload(self, project_id: str, document_id: str, filename: str, content: bytes) -> tuple[str, str]:
        upload_dir = self._upload_dir(project_id)
        await aiofiles.os.makedirs(str(upload_dir), exist_ok=True)

        ext = Path(filename).suffix
        dest = upload_dir / f"{document_id}{ext}"

        async with aiofiles.open(str(dest), "wb") as f:
            await f.write(content)

        content_hash = hashlib.sha256(content).hexdigest()
        return str(dest), content_hash

    async def read_file(self, path: str) -> bytes:
        async with aiofiles.open(path, "rb") as f:
            return await f.read()

    async def write_file(self, path: str, content: bytes) -> None:
        await aiofiles.os.makedirs(str(Path(path).parent), exist_ok=True)
        async with aiofiles.open(path, "wb") as f:
            await f.write(content)

    async def write_text(self, path: str, content: str) -> None:
        await aiofiles.os.makedirs(str(Path(path).parent), exist_ok=True)
        async with aiofiles.open(path, "w", encoding="utf-8") as f:
            await f.write(content)

    async def file_exists(self, path: str) -> bool:
        return Path(path).exists()

    async def delete_file(self, path: str) -> None:
        p = Path(path)
        if p.exists():
            await aiofiles.os.remove(path)

    def get_project_root(self, project_id: str) -> str:
        return str(self._project_dir(project_id))


file_store = FileStore()
