import pytest
import json
from httpx import AsyncClient, ASGITransport
from macf2.web.app import create_app
from macf2.models import ConferenceStatus


@pytest.fixture
def app(tmp_path):
    return create_app(topic="Integration Test", workspace_dir=tmp_path)


@pytest.mark.asyncio
async def test_full_conference_flow(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Register 3 agents
        r1 = await client.post("/api/register", json={"name": "Architect", "role": "designs systems"})
        assert r1.status_code == 200
        a1 = r1.json()["agent_id"]

        r2 = await client.post("/api/register", json={"name": "Developer", "role": "writes code"})
        assert r2.status_code == 200
        a2 = r2.json()["agent_id"]

        r3 = await client.post("/api/register", json={"name": "Reviewer", "role": "reviews code"})
        assert r3.status_code == 200
        a3 = r3.json()["agent_id"]

        # Start conference
        resp = await client.post("/api/start")
        assert resp.status_code == 200

        # Verify conference is active
        resp = await client.get("/api/conference")
        assert resp.json()["status"] == "active"
        assert resp.json()["current_round"] == 1

        # Agents are listed
        resp = await client.get("/api/agents")
        assert len(resp.json()) == 3


@pytest.mark.asyncio
async def test_file_operations_via_conference(app, tmp_path):
    conference = app.state.conference
    fm = app.state.file_manager

    # Create and manipulate files
    fm.create_file("design.md", "# Design\n")
    a1 = conference.register_agent("Writer")
    a2 = conference.register_agent("Editor")

    # Lock, write, release
    assert fm.acquire_lock("design.md", a1) is True
    fm.write_file("design.md", "# Updated Design\n", a1)
    assert fm.read_file("design.md") == "# Updated Design\n"

    # Other agent can't write
    with pytest.raises(PermissionError):
        fm.write_file("design.md", "nope", a2)

    # Release and other agent can now lock
    fm.release_lock("design.md", a1)
    assert fm.acquire_lock("design.md", a2) is True


@pytest.mark.asyncio
async def test_conference_completes_on_votes(app):
    conference = app.state.conference

    a1 = conference.register_agent("A1")
    a2 = conference.register_agent("A2")
    a3 = conference.register_agent("A3")
    conference.start()

    # Round 1: majority votes to end
    conference.vote_to_end(a1)
    conference.vote_to_end(a2)
    conference.post_message(a3, "I disagree but ok")

    assert conference.state.status == ConferenceStatus.COMPLETED


@pytest.mark.asyncio
async def test_moderator_can_halt(app):
    conference = app.state.conference

    a1 = conference.register_agent("A1")
    a2 = conference.register_agent("A2")
    conference.start()

    conference.halt("Going off the rails")
    assert conference.state.status == ConferenceStatus.HALTED
