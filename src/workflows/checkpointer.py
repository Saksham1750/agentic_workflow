import logging
import aiosqlite
from src.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_checkpointer = None


async def get_checkpointer():
    global _checkpointer
    if _checkpointer is not None:
        return _checkpointer

    try:
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        conn = await aiosqlite.connect(settings.CHECKPOINT_DB_PATH)
        saver = AsyncSqliteSaver(conn)
        await saver.setup()
        _checkpointer = saver
        logger.info("Checkpointer initialized at %s", settings.CHECKPOINT_DB_PATH)
        return saver
    except Exception as e:
        logger.warning("Checkpointer unavailable: %s", e)
        return None


async def close_checkpointer():
    global _checkpointer
    if _checkpointer is not None:
        await _checkpointer.conn.close()
        _checkpointer = None
