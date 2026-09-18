import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from src.main import app
from src.database import init_db


@pytest_asyncio.fixture
async def client():
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
