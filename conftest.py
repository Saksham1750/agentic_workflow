import os
import tempfile

_test_tmpdir = tempfile.mkdtemp()
_db_path = os.path.join(_test_tmpdir, "test.db")
os.environ["SQLITE_DB_PATH"] = _db_path
os.environ["DATA_ROOT"] = os.path.join(_test_tmpdir, "data")
os.environ["CHROMA_PERSIST_DIR"] = os.path.join(_test_tmpdir, "chroma")

from src.database import engine, Base, init_db
import src.models  # noqa: F401


def pytest_configure(config):
    import asyncio
    asyncio.get_event_loop().run_until_complete(init_db())
    print(f"\n[TEST SETUP] DB path: {_db_path}")
    print(f"[TEST SETUP] Engine URL: {engine.url}")


def pytest_sessionstart(session):
    import asyncio

    async def verify():
        from sqlalchemy import text
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
            tables = result.fetchall()
            print(f"[TEST SETUP] Tables in DB: {tables}")

    asyncio.get_event_loop().run_until_complete(verify())
