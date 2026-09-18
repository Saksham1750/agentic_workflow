import logging
import aiosqlite

from src.services.seed_service import seed_patterns

logger = logging.getLogger(__name__)

_checkpointer_instance = None


async def initialize_checkpointer():
    global _checkpointer_instance
    if _checkpointer_instance is not None:
        return _checkpointer_instance

    try:
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        conn = await aiosqlite.connect("./data/checkpoints.sqlite")
        saver = AsyncSqliteSaver(conn)
        await saver.setup()
        _checkpointer_instance = saver
        logger.info("Checkpointer initialized")
        return saver
    except Exception as e:
        logger.warning("Checkpointer init skipped: %s", e)
        return None


async def initialize_seeds():
    await seed_patterns()
