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
async def auth_and_project(client):
    await client.post("/auth/register", json={"username": "wfuser", "password": "pass123"})
    login = await client.post("/auth/login", json={"username": "wfuser", "password": "pass123"})
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    proj_resp = await client.post("/projects", json={"name": "WF Project"}, headers=headers)
    project_id = proj_resp.json()["id"]

    return headers, project_id


@pytest.mark.asyncio
async def test_list_workflows(client, auth_and_project):
    headers, _ = auth_and_project
    resp = await client.get("/workflows", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["workflows"]) == 3
    names = [w["name"] for w in data["workflows"]]
    assert "requirements" in names


@pytest.mark.asyncio
async def test_get_workflow_graph(client, auth_and_project):
    headers, _ = auth_and_project
    resp = await client.get("/workflows/requirements/graph", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "requirements"
    assert "document_ingestion" in data["nodes"]
    assert "validation" in data["nodes"]
    assert "interrupt_before" in data


@pytest.mark.asyncio
async def test_trigger_requirements_workflow(client, auth_and_project):
    headers, project_id = auth_and_project
    resp = await client.post(
        f"/projects/{project_id}/workflows/requirements",
        json={},
        headers=headers,
    )
    assert resp.status_code == 202
    data = resp.json()
    assert data["workflow_type"] == "requirements"
    assert data["status"] in ("pending", "running")
    assert "id" in data


@pytest.mark.asyncio
async def test_list_runs(client, auth_and_project):
    headers, project_id = auth_and_project
    await client.post(
        f"/projects/{project_id}/workflows/requirements",
        json={},
        headers=headers,
    )

    resp = await client.get(f"/projects/{project_id}/runs", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1


@pytest.mark.asyncio
async def test_get_run(client, auth_and_project):
    headers, project_id = auth_and_project
    create_resp = await client.post(
        f"/projects/{project_id}/workflows/requirements",
        json={},
        headers=headers,
    )
    run_id = create_resp.json()["id"]

    resp = await client.get(f"/projects/{project_id}/runs/{run_id}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == run_id


@pytest.mark.asyncio
async def test_trigger_invalid_workflow_returns_400(client, auth_and_project):
    headers, project_id = auth_and_project
    resp = await client.post(
        f"/projects/{project_id}/workflows/invalid_workflow",
        json={},
        headers=headers,
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_idempotency_key_returns_same_run(client, auth_and_project):
    headers, project_id = auth_and_project
    key = "test-idempotency-key-123"

    resp1 = await client.post(
        f"/projects/{project_id}/workflows/requirements",
        json={"idempotency_key": key},
        headers=headers,
    )
    resp2 = await client.post(
        f"/projects/{project_id}/workflows/requirements",
        json={"idempotency_key": key},
        headers=headers,
    )
    assert resp1.json()["id"] == resp2.json()["id"]


@pytest.mark.asyncio
async def test_tasks_crud(client, auth_and_project):
    headers, project_id = auth_and_project
    create_resp = await client.post(
        f"/projects/{project_id}/workflows/requirements",
        json={},
        headers=headers,
    )
    run_id = create_resp.json()["id"]

    task_resp = await client.post(
        f"/projects/{project_id}/tasks?run_id={run_id}",
        json={"title": "Task 1", "description": "Do something"},
        headers=headers,
    )
    assert task_resp.status_code == 201
    task_id = task_resp.json()["id"]
    assert task_resp.json()["title"] == "Task 1"

    list_resp = await client.get(
        f"/projects/{project_id}/tasks?run_id={run_id}",
        headers=headers,
    )
    assert list_resp.status_code == 200
    assert list_resp.json()["total"] >= 1

    patch_resp = await client.patch(
        f"/projects/{project_id}/tasks/{task_id}",
        json={"title": "Updated Task"},
        headers=headers,
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["title"] == "Updated Task"
