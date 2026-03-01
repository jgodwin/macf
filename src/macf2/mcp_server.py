from __future__ import annotations

import asyncio
import json
from pathlib import Path
from mcp.server.fastmcp import FastMCP, Context

from macf2.conference import ConferenceManager
from macf2.file_manager import FileManager


def create_mcp_server(
    topic: str = "Untitled Conference",
    goal: str = "",
    roles: list | None = None,
    workspace_dir: Path | None = None,
    mcp_host: str = "127.0.0.1",
    mcp_port: int = 8001,
) -> dict:
    """Create an MCP server wired to a conference and file manager.

    Returns a dict with keys: mcp, conference, file_manager.
    """
    if workspace_dir is None:
        workspace_dir = Path.cwd() / "workspace"

    conference = ConferenceManager(topic=topic, goal=goal, roles=roles)
    file_manager = FileManager(workspace_dir=workspace_dir)

    mcp = FastMCP(
        name="MACF2 Conference",
        instructions=(
            f"You are participating in a multi-agent conference on: {topic}. "
            "Use the provided tools to collaborate with other agents. "
            "Each round, you must either post a message, pass, or vote to end."
        ),
        host=mcp_host,
        port=mcp_port,
    )

    # --- Session-to-agent mapping ---
    _session_agents: dict[str, str] = {}  # client_id -> agent_id

    # --- File lock conditions for blocking acquire ---
    _file_lock_conditions: dict[str, asyncio.Condition] = {}

    def _get_file_condition(file_path: str) -> asyncio.Condition:
        if file_path not in _file_lock_conditions:
            _file_lock_conditions[file_path] = asyncio.Condition()
        return _file_lock_conditions[file_path]

    @mcp.tool()
    async def register_agent(name: str, role: str = "") -> str:
        """Register yourself as a conference participant. Returns your agent_id
        and a full briefing with the topic, goal, your role, other participants,
        and the round protocol. You must call this before any other action.
        Call get_available_roles first to see which roles are open.
        This will block until the conference has been configured by the moderator."""
        await conference.wait_for_configuration()
        agent_id = conference.register_agent(name, role=role)
        briefing = conference.get_briefing(agent_id)
        return json.dumps({
            "agent_id": agent_id,
            "topic": conference.state.topic,
            "briefing": briefing,
        })

    @mcp.tool()
    async def get_available_roles() -> str:
        """List pre-defined roles that haven't been claimed yet.
        Call this before register_agent to see which roles you can take.
        This will block until the conference has been configured by the moderator."""
        await conference.wait_for_configuration()
        return json.dumps(conference.get_available_roles())

    @mcp.tool()
    def get_conference_status() -> str:
        """Get the current conference status, topic, and round number."""
        return json.dumps({
            "topic": conference.state.topic,
            "status": conference.state.status.value,
            "current_round": conference.state.current_round,
            "agent_count": len(conference._active_agent_ids()),
        })

    @mcp.tool()
    def post_message(agent_id: str, content: str) -> str:
        """Post a message to the conference board for the current round.
        You can only post once per round."""
        conference.post_message(agent_id, content)
        return json.dumps({"status": "posted", "round": conference.state.current_round})

    @mcp.tool()
    def pass_turn(agent_id: str) -> str:
        """Pass your turn this round without posting a message."""
        conference.pass_turn(agent_id)
        return json.dumps({"status": "passed", "round": conference.state.current_round})

    @mcp.tool()
    def vote_to_end(agent_id: str) -> str:
        """Vote to end the conference. If a majority votes, the conference ends."""
        conference.vote_to_end(agent_id)
        return json.dumps({
            "status": "voted",
            "conference_status": conference.state.status.value,
        })

    @mcp.tool()
    def get_board() -> str:
        """Get all messages posted to the conference board."""
        return json.dumps(conference.get_board(), default=str)

    @mcp.tool()
    def get_round_info() -> str:
        """Get info about the current round: who has acted, who is pending."""
        return json.dumps(conference.get_round_info())

    @mcp.tool()
    def get_agents() -> str:
        """List all connected agents and their current status."""
        return json.dumps(conference.get_agents_info())

    # --- File tools ---

    @mcp.tool()
    async def create_shared_file(file_path: str, content: str = "") -> str:
        """Create a new shared file that all agents can collaborate on.
        This will block until the conference has been configured by the moderator."""
        await conference.wait_for_configuration()
        file_manager.create_file(file_path, content)
        return json.dumps({"status": "created", "file": file_path})

    @mcp.tool()
    def list_shared_files() -> str:
        """List all shared files in the workspace."""
        return json.dumps(file_manager.list_files())

    @mcp.tool()
    def read_shared_file(file_path: str) -> str:
        """Read the contents of a shared file."""
        content = file_manager.read_file(file_path)
        lock = file_manager.get_lock_info(file_path)
        return json.dumps({
            "file": file_path,
            "content": content,
            "lock": lock,
        })

    LOCK_ACQUIRE_TIMEOUT = 180  # 3 minutes

    @mcp.tool()
    async def acquire_file_lock(agent_id: str, file_path: str) -> str:
        """Acquire an exclusive write lock on a shared file.
        Blocks until the lock is available (up to 3 minutes). Only the lock
        holder can write. Also blocks until the conference has been configured."""
        await conference.wait_for_configuration()
        cond = _get_file_condition(file_path)
        deadline = asyncio.get_event_loop().time() + LOCK_ACQUIRE_TIMEOUT
        async with cond:
            while not file_manager.acquire_lock(file_path, agent_id):
                remaining = deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    return json.dumps({"acquired": False, "file": file_path,
                                       "error": "Timed out waiting for lock"})
                try:
                    await asyncio.wait_for(cond.wait(), timeout=min(remaining, 5.0))
                except asyncio.TimeoutError:
                    pass  # Retry — lock may have expired
        return json.dumps({"acquired": True, "file": file_path})

    @mcp.tool()
    async def release_file_lock(agent_id: str, file_path: str) -> str:
        """Release your write lock on a shared file."""
        file_manager.release_lock(file_path, agent_id)
        cond = _get_file_condition(file_path)
        async with cond:
            cond.notify_all()
        return json.dumps({"released": True, "file": file_path})

    @mcp.tool()
    async def write_shared_file(agent_id: str, file_path: str, content: str) -> str:
        """Write to a shared file. You must hold the lock first (acquire_file_lock).
        This will block until the conference has been configured by the moderator."""
        await conference.wait_for_configuration()
        file_manager.write_file(file_path, content, agent_id)
        return json.dumps({"status": "written", "file": file_path})

    # --- MCP Prompt ---

    @mcp.prompt()
    def conference_briefing(agent_id: str) -> str:
        """Get your full conference briefing: topic, goal, your role,
        other participants, and the round protocol."""
        return conference.get_briefing(agent_id)

    return {"mcp": mcp, "conference": conference, "file_manager": file_manager}
