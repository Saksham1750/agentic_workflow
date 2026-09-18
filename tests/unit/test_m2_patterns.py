import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from src.main import app


@pytest_asyncio.fixture
async def client():
    from src.database import init_db
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def auth_header(client):
    await client.post("/auth/register", json={"username": "patternuser", "password": "pass123"})
    login = await client.post("/auth/login", json={"username": "patternuser", "password": "pass123"})
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_create_pattern(client, auth_header):
    resp = await client.post("/patterns", json={
        "name": "Test Pattern",
        "intent": "Test intent",
        "structure": "Test structure",
        "when_to_use": "Test usage",
        "strengths": "Test strengths",
        "tags": ["test", "example"],
    }, headers=auth_header)
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Test Pattern"
    assert data["intent"] == "Test intent"
    assert data["tags"] == ["test", "example"]
    assert "id" in data


@pytest.mark.asyncio
async def test_list_patterns(client, auth_header):
    await client.post("/patterns", json={
        "name": "Pattern A",
        "intent": "Intent A",
        "structure": "Structure A",
        "when_to_use": "Usage A",
    }, headers=auth_header)
    await client.post("/patterns", json={
        "name": "Pattern B",
        "intent": "Intent B",
        "structure": "Structure B",
        "when_to_use": "Usage B",
    }, headers=auth_header)

    resp = await client.get("/patterns", headers=auth_header)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 2


@pytest.mark.asyncio
async def test_get_pattern(client, auth_header):
    create_resp = await client.post("/patterns", json={
        "name": "Get Me",
        "intent": "Test",
        "structure": "Test",
        "when_to_use": "Test",
    }, headers=auth_header)
    pattern_id = create_resp.json()["id"]

    resp = await client.get(f"/patterns/{pattern_id}", headers=auth_header)
    assert resp.status_code == 200
    assert resp.json()["name"] == "Get Me"


@pytest.mark.asyncio
async def test_update_pattern(client, auth_header):
    create_resp = await client.post("/patterns", json={
        "name": "Update Me",
        "intent": "Old intent",
        "structure": "Old structure",
        "when_to_use": "Old usage",
    }, headers=auth_header)
    pattern_id = create_resp.json()["id"]

    resp = await client.patch(f"/patterns/{pattern_id}", json={
        "intent": "New intent",
        "tags": ["updated"],
    }, headers=auth_header)
    assert resp.status_code == 200
    assert resp.json()["intent"] == "New intent"
    assert resp.json()["tags"] == ["updated"]


@pytest.mark.asyncio
async def test_delete_pattern(client, auth_header):
    create_resp = await client.post("/patterns", json={
        "name": "Delete Me",
        "intent": "Test",
        "structure": "Test",
        "when_to_use": "Test",
    }, headers=auth_header)
    pattern_id = create_resp.json()["id"]

    resp = await client.delete(f"/patterns/{pattern_id}", headers=auth_header)
    assert resp.status_code == 204

    get_resp = await client.get(f"/patterns/{pattern_id}", headers=auth_header)
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_search_patterns(client, auth_header):
    await client.post("/patterns", json={
        "name": "ReAct Agent",
        "intent": "Reasoning and acting with tools",
        "structure": "Loop of thought-action-observation",
        "when_to_use": "Multi-step tasks with tools",
        "tags": ["reasoning", "tool-use"],
    }, headers=auth_header)

    resp = await client.post("/patterns/search", json={
        "query": "reasoning with tools",
        "n_results": 5,
    }, headers=auth_header)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1


@pytest.mark.asyncio
async def test_search_patterns_with_tags(client, auth_header):
    await client.post("/patterns", json={
        "name": "Tagged Pattern",
        "intent": "Test",
        "structure": "Test",
        "when_to_use": "Test",
        "tags": ["unique-tag-123"],
    }, headers=auth_header)

    resp = await client.post("/patterns/search", json={
        "query": "test",
        "tags": ["unique-tag-123"],
        "n_results": 5,
    }, headers=auth_header)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_bulk_import_patterns(client, auth_header):
    resp = await client.post("/patterns/bulk", json=[
        {
            "name": "Bulk A",
            "intent": "Bulk intent A",
            "structure": "Bulk structure A",
            "when_to_use": "Bulk usage A",
        },
        {
            "name": "Bulk B",
            "intent": "Bulk intent B",
            "structure": "Bulk structure B",
            "when_to_use": "Bulk usage B",
        },
    ], headers=auth_header)
    assert resp.status_code == 201
    data = resp.json()
    assert data["created"] == 2
    assert data["total"] == 2


@pytest.mark.asyncio
async def test_create_duplicate_pattern_returns_409(client, auth_header):
    await client.post("/patterns", json={
        "name": "Unique Pattern",
        "intent": "Test",
        "structure": "Test",
        "when_to_use": "Test",
    }, headers=auth_header)

    resp = await client.post("/patterns", json={
        "name": "Unique Pattern",
        "intent": "Test 2",
        "structure": "Test 2",
        "when_to_use": "Test 2",
    }, headers=auth_header)
    assert resp.status_code == 409
