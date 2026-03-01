import pytest
import json
from httpx import AsyncClient, ASGITransport
from macf.web.app import create_app


@pytest.fixture
def app(tmp_path):
    return create_app(topic="Test Conference", sessions_dir=tmp_path / "sessions")


@pytest.mark.asyncio
async def test_health_endpoint(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_conference_status(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/conference")
        assert resp.status_code == 200
        data = resp.json()
        assert data["topic"] == "Test Conference"


@pytest.mark.asyncio
async def test_agents_endpoint(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/agents")
        assert resp.status_code == 200
        assert resp.json() == []


@pytest.mark.asyncio
async def test_moderator_message(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/register", json={"name": "A1"})
        assert resp.status_code == 200
        resp = await client.post("/api/register", json={"name": "A2"})
        assert resp.status_code == 200
        resp = await client.post("/api/start")
        assert resp.status_code == 200
        resp = await client.post(
            "/api/moderator/message",
            json={"content": "Focus please"},
        )
        assert resp.status_code == 200


@pytest.mark.asyncio
async def test_halt_endpoint(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/register", json={"name": "A1"})
        resp = await client.post("/api/register", json={"name": "A2"})
        resp = await client.post("/api/start")
        resp = await client.post("/api/halt", json={"reason": "Off topic"})
        assert resp.status_code == 200
        resp = await client.get("/api/conference")
        assert resp.json()["status"] == "halted"


@pytest.mark.asyncio
async def test_dashboard_serves_html(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]


@pytest.mark.asyncio
async def test_configure_conference(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/configure", json={
            "topic": "Design a CLI",
            "goal": "Build a working tool",
            "roles": [{"name": "Architect", "description": "designs systems", "instructions": "Focus on structure"}],
        })
        assert resp.status_code == 200
        resp = await client.get("/api/conference")
        data = resp.json()
        assert data["topic"] == "Design a CLI"
        assert data["goal"] == "Build a working tool"


@pytest.mark.asyncio
async def test_get_roles(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post("/api/configure", json={
            "topic": "Test",
            "roles": [{"name": "A1", "description": "role1"}, {"name": "A2", "description": "role2"}],
        })
        resp = await client.get("/api/roles")
        assert resp.status_code == 200
        assert len(resp.json()) == 2


@pytest.mark.asyncio
async def test_get_agent_prompt(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/prompt")
        assert resp.status_code == 200
        data = resp.json()
        assert "prompt" in data
        assert "get_available_roles" in data["prompt"]
        assert "mcp_url" in data
