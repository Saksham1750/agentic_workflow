import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from src.main import app


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_register_and_login(client):
    reg_resp = await client.post("/auth/register", json={"username": "testuser", "password": "testpass"})
    assert reg_resp.status_code == 201
    data = reg_resp.json()
    assert "user_id" in data
    assert data["username"] == "testuser"

    login_resp = await client.post("/auth/login", json={"username": "testuser", "password": "testpass"})
    assert login_resp.status_code == 200
    login_data = login_resp.json()
    assert "access_token" in login_data
    assert login_data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_auth_me(client):
    reg_resp = await client.post("/auth/register", json={"username": "meuser", "password": "mepass"})
    assert reg_resp.status_code == 201

    login_resp = await client.post("/auth/login", json={"username": "meuser", "password": "mepass"})
    token = login_resp.json()["access_token"]

    me_resp = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_resp.status_code == 200
    assert me_resp.json()["username"] == "meuser"


@pytest.mark.asyncio
async def test_project_crud(client):
    reg_resp = await client.post("/auth/register", json={"username": "projuser", "password": "projpass"})
    login_resp = await client.post("/auth/login", json={"username": "projuser", "password": "projpass"})
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    create_resp = await client.post("/projects", json={"name": "Test Project", "description": "A test"}, headers=headers)
    assert create_resp.status_code == 201
    project = create_resp.json()
    pid = project["id"]
    assert project["name"] == "Test Project"
    assert project["status"] == "draft"

    list_resp = await client.get("/projects", headers=headers)
    assert list_resp.status_code == 200
    assert list_resp.json()["total"] >= 1

    get_resp = await client.get(f"/projects/{pid}", headers=headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == pid

    patch_resp = await client.patch(f"/projects/{pid}", json={"name": "Updated"}, headers=headers)
    assert patch_resp.status_code == 200
    assert patch_resp.json()["name"] == "Updated"


@pytest.mark.asyncio
async def test_project_404_for_other_user(client):
    reg1 = await client.post("/auth/register", json={"username": "user1", "password": "pass1"})
    login1 = await client.post("/auth/login", json={"username": "user1", "password": "pass1"})
    token1 = login1.json()["access_token"]

    reg2 = await client.post("/auth/register", json={"username": "user2", "password": "pass2"})
    login2 = await client.post("/auth/login", json={"username": "user2", "password": "pass2"})
    token2 = login2.json()["access_token"]

    create_resp = await client.post(
        "/projects",
        json={"name": "Private"},
        headers={"Authorization": f"Bearer {token1}"},
    )
    pid = create_resp.json()["id"]

    get_resp = await client.get(
        f"/projects/{pid}",
        headers={"Authorization": f"Bearer {token2}"},
    )
    assert get_resp.status_code == 404
