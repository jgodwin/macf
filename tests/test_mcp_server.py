import pytest
import json
from macf2.mcp_server import create_mcp_server


@pytest.fixture
def mcp_app(tmp_path):
    """Create a fresh MCP server with conference for each test."""
    return create_mcp_server(topic="Test conference", sessions_dir=tmp_path / "sessions")


@pytest.mark.asyncio
async def test_list_tools(mcp_app):
    mcp = mcp_app["mcp"]
    # _tool_manager.list_tools() is synchronous and returns Tool objects
    tools = mcp._tool_manager.list_tools()
    tool_names = {t.name for t in tools}
    assert "register_agent" in tool_names
    assert "post_message" in tool_names
    assert "pass_turn" in tool_names
    assert "vote_to_end" in tool_names
    assert "get_board" in tool_names
    assert "get_round_info" in tool_names
    assert "get_agents" in tool_names
    assert "acquire_file_lock" in tool_names
    assert "release_file_lock" in tool_names
    assert "read_shared_file" in tool_names
    assert "write_shared_file" in tool_names
    assert "list_shared_files" in tool_names
    assert "create_shared_file" in tool_names


@pytest.mark.asyncio
async def test_register_and_get_agents(mcp_app):
    conference = mcp_app["conference"]
    agent_id = conference.register_agent("TestAgent", role="tester")
    agents = conference.get_agents_info()
    assert len(agents) == 1
    assert agents[0]["name"] == "TestAgent"


@pytest.mark.asyncio
async def test_full_round_flow(mcp_app):
    conference = mcp_app["conference"]
    a1 = conference.register_agent("Agent1")
    a2 = conference.register_agent("Agent2")
    conference.start()
    conference.post_message(a1, "Let's collaborate")
    conference.pass_turn(a2)
    assert conference.state.current_round == 2
