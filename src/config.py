import json
import os
from pathlib import Path
from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    JWT_SECRET: str = "dev-secret-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_MINUTES: int = 60

    GROQ_API_KEY: str = ""
    LLM_MODEL: str = "qwen/qwen3.8-27b"

    SQLITE_DB_PATH: str = "./data/app.db"
    CHECKPOINT_DB_PATH: str = "./data/checkpoints.sqlite"
    CHROMA_PERSIST_DIR: str = "./data/chroma"
    DATA_ROOT: str = "./data"

    MAX_UPLOAD_SIZE_MB: int = 50
    COST_CEILING_PER_RUN: float = 10.0
    MODEL_PRICING: str = '{"gpt-5.5":{"input":0.01,"output":0.03},"gpt-5.4":{"input":0.005,"output":0.015}}'

    ALLOWED_MIME_TYPES: list[str] = [
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "text/markdown",
        "text/plain",
        "application/octet-stream",
    ]

    @property
    def pricing_table(self) -> dict:
        return json.loads(self.MODEL_PRICING)

    @property
    def max_upload_bytes(self) -> int:
        return self.MAX_UPLOAD_SIZE_MB * 1024 * 1024

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
