import ast
import json
import logging
import textwrap
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
        tasks: list[dict] | None = None,
        architecture_json: dict | None = None,
        selected_patterns: list[dict] | None = None,
    ) -> str:
        import zipfile

        workspace_dir = self._workspace_dir(project_id, run_id)
        runs_dir = Path(settings.DATA_ROOT) / "projects" / project_id / "runs" / run_id
        runs_dir.mkdir(parents=True, exist_ok=True)
        bundle_path = str(runs_dir / "bundle.zip")

        manifest = {
            "version": "1.0",
            "run_id": run_id,
            "project_id": project_id,
            "task_files": task_file_map or {},
            "files": [],
        }

        readme_content = self._generate_readme(
            project_id, run_id, task_file_map, tasks, architecture_json, selected_patterns,
        )

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
            zf.writestr("README.md", readme_content)

        logger.info("Created bundle at %s with %d files", bundle_path, len(manifest["files"]))
        return bundle_path

    def _detect_framework(self, files: list[dict]) -> str:
        content_all = " ".join(f.get("content", "") for f in files)
        if "FastAPI" in content_all or "fastapi" in content_all:
            return "fastapi"
        if "Flask" in content_all:
            return "flask"
        if "Django" in content_all:
            return "django"
        return "generic"

    def _detect_database(self, files: list[dict]) -> str:
        content_all = " ".join(f.get("content", "") for f in files)
        if "sqlalchemy" in content_all.lower():
            return "SQLAlchemy"
        if "motor" in content_all.lower() or "pymongo" in content_all.lower():
            return "MongoDB"
        if "aiosqlite" in content_all.lower():
            return "SQLite"
        if "asyncpg" in content_all.lower():
            return "PostgreSQL"
        return "None detected"

    def _build_project_tree(self, files: list[dict]) -> str:
        paths = sorted(f.get("path", "") for f in files)
        tree_lines = []
        prev_parts = []
        for p in paths:
            parts = p.split("/")
            for i, part in enumerate(parts[:-1]):
                prefix = "    " * i
                if i < len(prev_parts) and prev_parts[i] == part:
                    continue
                tree_lines.append(f"{prefix}{part}/")
            prev_parts = parts[:-1]
            indent = "    " * (len(parts) - 1)
            tree_lines.append(f"{indent}{parts[-1]}")

        seen = set()
        unique = []
        for line in tree_lines:
            if line not in seen:
                seen.add(line)
                unique.append(line)

        return "\n".join(unique[:80])

    def _generate_readme(
        self,
        project_id: str,
        run_id: str,
        task_file_map: dict[str, list[str]] | None,
        tasks: list[dict] | None,
        architecture_json: dict | None,
        selected_patterns: list[dict] | None,
    ) -> str:
        task_count = len(tasks) if tasks else 0
        all_files = []
        if task_file_map:
            for f_list in task_file_map.values():
                all_files.extend(f_list)
        file_count = len(set(all_files))

        pattern_names = [p.get("name", "Unknown") for p in (selected_patterns or [])]
        components = architecture_json.get("components", []) if architecture_json else []
        framework = self._detect_framework([{"content": "", "path": ""}])
        database = self._detect_database([{"content": "", "path": ""}])

        tree = self._build_project_tree([{"path": p} for p in all_files])

        task_section = ""
        if tasks:
            task_section = "## Task Breakdown\n\n"
            task_section += "| # | Task | Description | Target Files |\n"
            task_section += "|---|------|-------------|-------------|\n"
            for i, t in enumerate(tasks, 1):
                tid = t.get("task_id", f"T{i:03d}")
                title = t.get("title", "Untitled")
                desc = (t.get("description", "")[:80] + "...") if len(t.get("description", "")) > 80 else t.get("description", "")
                tfiles = ", ".join(t.get("target_files", [])[:3])
                if len(t.get("target_files", [])) > 3:
                    tfiles += f" +{len(t.get('target_files', [])) - 3} more"
                task_section += f"| {tid} | {title} | {desc} | {tfiles} |\n"
            task_section += "\n"

        arch_section = ""
        if components:
            arch_section = "## Architecture\n\n"
            arch_section += "### Components\n\n"
            for c in components:
                name = c.get("name", "Unknown")
                desc = c.get("description", "No description")
                arch_section += f"#### `{name}`\n{desc}\n\n"

            risks = architecture_json.get("risks", [])
            if risks:
                arch_section += "### Risks & Mitigations\n\n"
                arch_section += "| Risk | Severity | Mitigation |\n"
                arch_section += "|------|----------|------------|\n"
                for r in risks:
                    arch_section += f"| {r.get('risk', 'N/A')} | {r.get('severity', 'N/A')} | {r.get('mitigation', 'N/A')} |\n"
                arch_section += "\n"

        patterns_section = ""
        if pattern_names:
            patterns_section = "## Agentic Design Patterns\n\n"
            for p in selected_patterns or []:
                name = p.get("name", "Unknown")
                rationale = p.get("rationale", "No rationale")
                arch = p.get("architecture", {})
                prereqs = arch.get("prerequisites", [])
                arch_section_text = arch.get("architecture", "")
                patterns_section += f"### {name}\n"
                patterns_section += f"**Rationale:** {rationale}\n\n"
                if prereqs:
                    patterns_section += f"**Prerequisites:** {', '.join(prereqs)}\n\n"
                if arch_section_text:
                    patterns_section += f"**Architecture:** {arch_section_text}\n\n"

        components_list = ""
        if components:
            components_list = "### Component Details\n\n"
            for c in components:
                name = c.get("name", "Unknown")
                inputs = c.get("inputs", [])
                outputs = c.get("outputs", [])
                deps = c.get("dependencies", [])
                components_list += f"#### `{name}`\n"
                if inputs:
                    components_list += f"- **Inputs:** {', '.join(inputs)}\n"
                if outputs:
                    components_list += f"- **Outputs:** {', '.join(outputs)}\n"
                if deps:
                    components_list += f"- **Dependencies:** {', '.join(deps)}\n"
                components_list += "\n"

        return f"""# Generated Project

> Generated by **AI Agent Factory**
> Project ID: `{project_id}`
> Run ID: `{run_id}`

---

## Overview

This project was automatically generated from your BRD/PRD/TRD documents. It contains a complete, runnable codebase with all necessary files, configurations, and documentation.

| Property | Value |
|----------|-------|
| Total Files | {file_count} |
| Tasks Completed | {task_count} |
| Patterns Applied | {len(pattern_names)} |
| Framework | {framework.title()} |
| Database | {database} |

---

## Quick Start

### Prerequisites

- **Python 3.11** or higher (`python --version` to check)
- **pip** (comes with Python)
- **Git** (optional, for version control)

### Step-by-Step Setup

#### 1. Extract the Bundle

```bash
# Unzip the downloaded bundle
unzip bundle.zip -d my-project
cd my-project
```

#### 2. Create a Virtual Environment (Recommended)

```bash
# Create virtual environment
python -m venv venv

# Activate it:
# Windows (PowerShell):
venv\\Scripts\\Activate.ps1

# Windows (Command Prompt):
venv\\Scripts\\activate.bat

# macOS / Linux:
source venv/bin/activate
```

#### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

#### 4. Run the Application

**For FastAPI projects:**

```bash
# Development mode (auto-reload on code changes):
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Or:
python main.py
```

Then open your browser: **http://localhost:8000**

API documentation available at: **http://localhost:8000/docs**

**For other projects:**

```bash
python main.py
```

#### 5. Verify It Works

```bash
# Test the health endpoint (FastAPI projects):
curl http://localhost:8000/health

# Or open in browser:
# http://localhost:8000
```

---

## Project Structure

```
{tree}
```

---

## Configuration

### Environment Variables

Create a `.env` file in the project root if needed:

```env
# Application
APP_ENV=development
APP_DEBUG=true
APP_PORT=8000

# Database (if applicable)
DATABASE_URL=sqlite+aiosqlite:///./app.db

# API Keys (if applicable)
GROQ_API_KEY=your-groq-key-here
```

### Database Setup (if applicable)

```bash
# Initialize database tables (if using SQLAlchemy):
python -c "from main import app; print('App loaded successfully')"
```

---

{task_section}
{arch_section}
{components_list}
{patterns_section}
## API Endpoints (FastAPI Projects)

After starting the server, visit:
- **Interactive API docs:** http://localhost:8000/docs
- **Alternative docs:** http://localhost:8000/redoc

---

## Troubleshooting

### Common Issues

| Problem | Solution |
|---------|----------|
| `ModuleNotFoundError` | Run `pip install -r requirements.txt` |
| `Address already in use` | Change port: `uvicorn main:app --port 8001` |
| `Permission denied` (Windows) | Run PowerShell as Administrator |
| `python` not found | Try `python3` or check PATH |
| Database errors | Check `.env` for `DATABASE_URL` |

### Getting Help

1. Check the error message — it usually tells you what's wrong
2. Verify all dependencies are installed: `pip list`
3. Make sure you're in the project directory
4. Ensure the virtual environment is activated

---

## File Manifest

See `MANIFEST.json` for the complete file listing and task-to-file mapping.

Each task ID maps to the files it generated, helping you understand which part of the codebase corresponds to which requirement.

---

## Next Steps

1. **Review the code** — Read through generated files to understand the implementation
2. **Run tests** (if any): `pytest` or `python -m pytest`
3. **Customize** — Modify files to match your exact requirements
4. **Deploy** — Follow your deployment platform's instructions

---

*Generated by AI Agent Factory — {task_count} tasks, {len(pattern_names)} patterns, {file_count} files*
"""


workspace_service = WorkspaceService()
