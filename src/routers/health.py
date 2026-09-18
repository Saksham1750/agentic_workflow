from fastapi import APIRouter
from sqlalchemy import text

from src.database import async_session_factory
from src.vectorstore.chroma_client import check_chroma_health
from src.storage.file_store import file_store
from src.config import get_settings

router = APIRouter(tags=["health"])
settings = get_settings()


@router.get("/healthz")
async def health_check():
    checks = {}

    try:
        async with async_session_factory() as session:
            await session.execute(text("SELECT 1"))
        checks["sqlite"] = "ok"
    except Exception as e:
        checks["sqlite"] = f"error: {str(e)}"

    try:
        healthy = await check_chroma_health()
        checks["chromadb"] = "ok" if healthy else "error: heartbeat failed"
    except Exception as e:
        checks["chromadb"] = f"error: {str(e)}"

    try:
        from pathlib import Path
        data_root = Path(settings.DATA_ROOT)
        data_root.mkdir(parents=True, exist_ok=True)
        checks["filesystem"] = "ok"
    except Exception as e:
        checks["filesystem"] = f"error: {str(e)}"

    all_ok = all(v == "ok" for v in checks.values())
    return {"status": "healthy" if all_ok else "degraded", "checks": checks}
