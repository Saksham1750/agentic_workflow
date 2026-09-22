import sqlite3
import uuid
import logging
from datetime import datetime, timezone

from langchain_core.callbacks import BaseCallbackHandler

from src.config import get_settings

logger = logging.getLogger(__name__)


class TokenTrackingCallback(BaseCallbackHandler):
    def __init__(self, run_id: str, project_id: str, node_name: str):
        self.run_id = run_id
        self.project_id = project_id
        self.node_name = node_name
        self._total_input = 0
        self._total_output = 0
        self._model = ""
        self._provider = "groq"

    def on_llm_end(self, response, **kwargs):
        try:
            llm_output = getattr(response, "llm_output", None) or {}
            token_usage = llm_output.get("token_usage") or llm_output.get("usage") or {}

            if token_usage:
                self._total_input = token_usage.get("prompt_tokens", 0) or token_usage.get("input_tokens", 0) or 0
                self._total_output = token_usage.get("completion_tokens", 0) or token_usage.get("output_tokens", 0) or 0
                self._model = llm_output.get("model_name", "") or llm_output.get("model", "") or ""
                self._provider = "groq"
                self._persist()
        except Exception as e:
            logger.warning("TokenTrackingCallback failed to extract usage: %s", e)

    def _persist(self):
        total = self._total_input + self._total_output
        if total == 0:
            return

        settings = get_settings()
        cost_usd = 0.0
        try:
            pricing = settings.pricing_table
            model_key = self._model
            if model_key in pricing:
                p = pricing[model_key]
                cost_usd = (self._total_input / 1000.0) * p.get("input", 0.0) + (self._total_output / 1000.0) * p.get("output", 0.0)
        except Exception:
            pass

        try:
            conn = sqlite3.connect(settings.SQLITE_DB_PATH)
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO token_usage
                (id, run_id, project_id, node_name, model, provider,
                 input_tokens, output_tokens, total_tokens, cost_usd, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(uuid.uuid4()),
                    self.run_id,
                    self.project_id,
                    self.node_name,
                    self._model,
                    self._provider,
                    self._total_input,
                    self._total_output,
                    total,
                    cost_usd,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning("Failed to persist token usage: %s", e)
