import sqlite3
import logging
from datetime import datetime, timezone
from pathlib import Path

from src.config import get_settings

logger = logging.getLogger(__name__)


class ReportService:
    async def generate_report(self, run_id: str, project_id: str) -> str:
        settings = get_settings()
        conn = sqlite3.connect(settings.SQLITE_DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            run = self._get_run(conn, run_id)
            token_usages = self._get_token_usages(conn, run_id)
            spans = self._get_spans(conn, run_id)
        finally:
            conn.close()

        report_md = self._build_report(run, token_usages, spans)

        report_path = (
            Path(settings.DATA_ROOT)
            / "projects"
            / project_id
            / "runs"
            / run_id
            / "report.md"
        )
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report_md, encoding="utf-8")

        logger.info("Report generated for run %s at %s", run_id, report_path)
        return report_md

    def _get_run(self, conn: sqlite3.Connection, run_id: str) -> dict:
        cursor = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,))
        row = cursor.fetchone()
        if not row:
            return {"id": run_id, "workflow_type": "unknown", "status": "unknown"}
        return dict(row)

    def _get_token_usages(self, conn: sqlite3.Connection, run_id: str) -> list[dict]:
        cursor = conn.execute(
            "SELECT * FROM token_usage WHERE run_id = ? ORDER BY timestamp", (run_id,)
        )
        return [dict(row) for row in cursor.fetchall()]

    def _get_spans(self, conn: sqlite3.Connection, run_id: str) -> list[dict]:
        cursor = conn.execute(
            "SELECT * FROM trace_spans WHERE run_id = ? ORDER BY start_time", (run_id,)
        )
        return [dict(row) for row in cursor.fetchall()]

    def _build_report(self, run: dict, token_usages: list[dict], spans: list[dict]) -> str:
        sections = [
            self._build_header(run),
            self._build_workflow_summary(run, spans),
            self._build_token_breakdown(token_usages),
            self._build_cost_breakdown(token_usages),
            self._build_node_timing(spans),
            self._build_model_summary(token_usages),
        ]
        return "\n\n".join(s for s in sections if s)

    def _build_header(self, run: dict) -> str:
        return (
            f"# Workflow Execution Report\n\n"
            f"- **Run ID:** `{run.get('id', 'N/A')}`\n"
            f"- **Workflow Type:** {run.get('workflow_type', 'N/A')}\n"
            f"- **Status:** {run.get('status', 'N/A')}\n"
            f"- **Created:** {run.get('created_at', 'N/A')}\n"
            f"- **Completed:** {run.get('completed_at', 'N/A') or 'N/A'}\n"
        )

    def _build_workflow_summary(self, run: dict, spans: list[dict]) -> str:
        unique_nodes = set()
        for s in spans:
            attrs = s.get("attributes") or {}
            node = attrs.get("node.name") or ""
            if node:
                unique_nodes.add(node)

        duration = ""
        if run.get("created_at") and run.get("completed_at"):
            try:
                created = datetime.fromisoformat(run["created_at"])
                completed = datetime.fromisoformat(run["completed_at"])
                delta = (completed - created).total_seconds()
                duration = f"{delta:.1f}s"
            except (ValueError, TypeError):
                pass

        return (
            f"## Workflow Summary\n\n"
            f"- **Nodes Visited:** {len(unique_nodes)}\n"
            f"- **Total Spans:** {len(spans)}\n"
            f"- **Duration:** {duration or 'N/A'}\n"
        )

    def _build_token_breakdown(self, token_usages: list[dict]) -> str:
        if not token_usages:
            return "## Token Usage Breakdown\n\nNo LLM token usage recorded for this run.\n"

        node_map: dict[str, dict] = {}
        for tu in token_usages:
            node = tu.get("node_name", "unknown")
            if node not in node_map:
                node_map[node] = {
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                    "calls": 0,
                }
            node_map[node]["input_tokens"] += tu.get("input_tokens", 0)
            node_map[node]["output_tokens"] += tu.get("output_tokens", 0)
            node_map[node]["total_tokens"] += tu.get("total_tokens", 0)
            node_map[node]["calls"] += 1

        lines = [
            "## Token Usage Breakdown\n",
            "| Node | Calls | Input Tokens | Output Tokens | Total Tokens |",
            "|------|-------|-------------|--------------|-------------|",
        ]
        for node, data in sorted(node_map.items()):
            lines.append(
                f"| {node} | {data['calls']} | {data['input_tokens']:,} | {data['output_tokens']:,} | {data['total_tokens']:,} |"
            )

        total_in = sum(d["input_tokens"] for d in node_map.values())
        total_out = sum(d["output_tokens"] for d in node_map.values())
        total_all = sum(d["total_tokens"] for d in node_map.values())
        lines.append(f"| **Total** | **{len(token_usages)}** | **{total_in:,}** | **{total_out:,}** | **{total_all:,}** |")

        return "\n".join(lines) + "\n"

    def _build_cost_breakdown(self, token_usages: list[dict]) -> str:
        if not token_usages:
            return "## Cost Breakdown\n\nNo cost data recorded for this run.\n"

        settings = get_settings()
        node_costs: dict[str, float] = {}
        for tu in token_usages:
            node = tu.get("node_name", "unknown")
            node_costs[node] = node_costs.get(node, 0.0) + tu.get("cost_usd", 0.0)

        total_cost = sum(node_costs.values())
        ceiling = settings.COST_CEILING_PER_RUN

        lines = [
            "## Cost Breakdown\n",
            "| Node | Cost (USD) |",
            "|------|-----------|",
        ]
        for node, cost in sorted(node_costs.items()):
            lines.append(f"| {node} | ${cost:.6f} |")

        lines.append(f"| **Total** | **${total_cost:.6f}** |")
        lines.append(f"\n**Budget Ceiling:** ${ceiling:.2f}")
        if total_cost > ceiling:
            lines.append(f"\n> **WARNING:** Total cost (${total_cost:.6f}) exceeds budget ceiling (${ceiling:.2f})")
        else:
            lines.append(f"\n> Cost is within budget (${total_cost:.6f} / ${ceiling:.2f})")

        return "\n".join(lines) + "\n"

    def _build_node_timing(self, spans: list[dict]) -> str:
        if not spans:
            return "## Node Timing\n\nNo span data recorded for this run.\n"

        node_spans: dict[str, list[dict]] = {}
        for s in spans:
            attrs = s.get("attributes") or {}
            node = attrs.get("node.name") or s.get("name", "unknown")
            if node not in node_spans:
                node_spans[node] = []
            node_spans[node].append(s)

        lines = [
            "## Node Timing\n",
            "| Node | Duration (ms) | Status |",
            "|------|--------------|--------|",
        ]
        for node, node_span_list in sorted(node_spans.items()):
            for s in node_span_list:
                start = s.get("start_time")
                end = s.get("end_time")
                status = s.get("status_code", "OK")
                duration_ms = ""
                if start and end:
                    try:
                        start_dt = datetime.fromisoformat(start)
                        end_dt = datetime.fromisoformat(end)
                        duration_ms = f"{(end_dt - start_dt).total_seconds() * 1000:.1f}"
                    except (ValueError, TypeError):
                        pass
                lines.append(f"| {node} | {duration_ms or 'N/A'} | {status} |")

        return "\n".join(lines) + "\n"

    def _build_model_summary(self, token_usages: list[dict]) -> str:
        if not token_usages:
            return "## Model Summary\n\nNo model usage recorded for this run.\n"

        model_map: dict[str, dict] = {}
        for tu in token_usages:
            model = tu.get("model", "unknown")
            if model not in model_map:
                model_map[model] = {
                    "total_tokens": 0,
                    "cost_usd": 0.0,
                    "calls": 0,
                }
            model_map[model]["total_tokens"] += tu.get("total_tokens", 0)
            model_map[model]["cost_usd"] += tu.get("cost_usd", 0.0)
            model_map[model]["calls"] += 1

        lines = [
            "## Model Summary\n",
            "| Model | Calls | Total Tokens | Cost (USD) |",
            "|-------|-------|-------------|-----------|",
        ]
        for model, data in sorted(model_map.items()):
            lines.append(
                f"| {model} | {data['calls']} | {data['total_tokens']:,} | ${data['cost_usd']:.6f} |"
            )

        return "\n".join(lines) + "\n"


report_service = ReportService()
