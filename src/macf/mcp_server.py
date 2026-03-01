from __future__ import annotations

import asyncio
import json
from pathlib import Path
from mcp.server.fastmcp import FastMCP, Context

from macf.conference import ConferenceManager
from macf.file_manager import FileManager
from macf.models import AgentStatus, ConferenceStatus
from macf.transcript import generate_session_id


def create_mcp_server(
    topic: str = "Untitled Conference",
    goal: str = "",
    roles: list | None = None,
    workspace_dir: Path | None = None,  # kept for backwards compat; sessions_dir takes precedence
    sessions_dir: Path | None = None,
    mcp_host: str = "127.0.0.1",
    mcp_port: int = 8001,
) -> dict:
    """Create an MCP server wired to a conference and file manager.

    Returns a dict with keys: mcp, conference, file_manager, sessions_dir.
    """
    conference = ConferenceManager(topic=topic, goal=goal, roles=roles)

    if sessions_dir is None:
        sessions_dir = Path.cwd() / "sessions"

    session_id = generate_session_id(conference.state)
    session_dir = sessions_dir / session_id
    workspace_dir = session_dir / "workspace"

    print(f"Session directory: {session_dir}")

    file_manager = FileManager(workspace_dir=workspace_dir)

    mcp = FastMCP(
        name="MACF Conference",
        instructions=(
            f"You are participating in a multi-agent conference on: {topic}. "
            "Use the provided tools to collaborate with other agents. "
            "Each round, you must either post a message, pass, or vote to end. "
            "IMPORTANT: Use long timeouts (at least 300 seconds) for ALL tool calls — "
            "many tools block while waiting for the conference to be configured or for other agents to act."
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
    async def register_agent(name: str, role: str = "", ctx: Context = None) -> str:
        """Register yourself as a conference participant. Returns your agent_id
        and a full briefing with the topic, goal, your role, other participants,
        and the round protocol. You must call this before any other action.
        Call get_available_roles first to see which roles are open.
        This will block until the conference has been configured by the moderator."""
        conference.track_mcp_client(ctx.client_id)
        await conference.wait_for_configuration()
        agent_id = conference.register_agent(name, role=role, client_id=ctx.client_id)
        briefing = conference.get_briefing(agent_id)
        return json.dumps({
            "agent_id": agent_id,
            "topic": conference.state.topic,
            "briefing": briefing,
        })

    @mcp.tool()
    async def get_available_roles(ctx: Context = None) -> str:
        """List pre-defined roles that haven't been claimed yet.
        Call this before register_agent to see which roles you can take.
        This will block until the conference has been configured by the moderator."""
        conference.track_mcp_client(ctx.client_id)
        await conference.wait_for_configuration()
        return json.dumps(conference.get_available_roles())

    @mcp.tool()
    def get_conference_status(ctx: Context = None) -> str:
        """Get the current conference status, topic, and round number."""
        conference.track_mcp_client(ctx.client_id)
        return json.dumps({
            "topic": conference.state.topic,
            "status": conference.state.status.value,
            "current_round": conference.state.current_round,
            "agent_count": len(conference._active_agent_ids()),
        })

    @mcp.tool()
    def post_message(agent_id: str, content: str, ctx: Context = None) -> str:
        """Post a message to the conference board for the current round.
        You can only post once per round."""
        conference.track_mcp_client(ctx.client_id)
        conference.post_message(agent_id, content)
        return json.dumps({"status": "posted", "round": conference.state.current_round})

    @mcp.tool()
    def pass_turn(agent_id: str, ctx: Context = None) -> str:
        """Pass your turn this round without posting a message."""
        conference.track_mcp_client(ctx.client_id)
        conference.pass_turn(agent_id)
        return json.dumps({"status": "passed", "round": conference.state.current_round})

    @mcp.tool()
    def vote_to_end(agent_id: str, ctx: Context = None) -> str:
        """Vote to end the conference. If a majority votes, the conference ends."""
        conference.track_mcp_client(ctx.client_id)
        conference.vote_to_end(agent_id)
        return json.dumps({
            "status": "voted",
            "conference_status": conference.state.status.value,
        })

    @mcp.tool()
    def get_board(ctx: Context = None) -> str:
        """Get all messages posted to the conference board."""
        conference.track_mcp_client(ctx.client_id)
        return json.dumps(conference.get_board(), default=str)

    @mcp.tool()
    def get_round_info(ctx: Context = None) -> str:
        """Get info about the current round: who has acted, who is pending."""
        conference.track_mcp_client(ctx.client_id)
        return json.dumps(conference.get_round_info())

    @mcp.tool()
    def get_agents(ctx: Context = None) -> str:
        """List all connected agents and their current status."""
        conference.track_mcp_client(ctx.client_id)
        return json.dumps(conference.get_agents_info())

    @mcp.tool()
    async def wait_for_turn(agent_id: str, ctx: Context = None) -> str:
        """Block until it is your turn to act, then return round info.
        This is the recommended way to wait between rounds — do NOT poll
        get_round_info in a loop. This tool will return when:
        - It is your turn to act (your status becomes THINKING)
        - The conference ends or is halted
        Uses a 300-second timeout. If it times out, just call it again."""
        conference.track_mcp_client(ctx.client_id)
        conference._check_agent(agent_id)
        elapsed = 0
        while elapsed < 300:
            status = conference.state.status
            if status in (ConferenceStatus.COMPLETED, ConferenceStatus.HALTED):
                return json.dumps({
                    "status": status.value,
                    "message": "Conference has ended.",
                })
            if status == ConferenceStatus.ACTIVE:
                agent = conference.state.agents.get(agent_id)
                if agent and agent.status == AgentStatus.THINKING:
                    return json.dumps({
                        "status": "your_turn",
                        "round": conference.state.current_round,
                        **conference.get_round_info(),
                    })
            await asyncio.sleep(1)
            elapsed += 1
        return json.dumps({
            "status": "timeout",
            "message": "Timed out after 300s. Call wait_for_turn again to keep waiting.",
        })

    # --- File tools ---

    @mcp.tool()
    async def create_shared_file(file_path: str, content: str = "", ctx: Context = None) -> str:
        """Create a new shared file that all agents can collaborate on.
        This will block until the conference has been configured by the moderator."""
        conference.track_mcp_client(ctx.client_id)
        await conference.wait_for_configuration()
        file_manager.create_file(file_path, content)
        return json.dumps({"status": "created", "file": file_path})

    @mcp.tool()
    def list_shared_files(ctx: Context = None) -> str:
        """List all shared files in the workspace."""
        conference.track_mcp_client(ctx.client_id)
        return json.dumps(file_manager.list_files())

    @mcp.tool()
    def read_shared_file(file_path: str, ctx: Context = None) -> str:
        """Read the contents of a shared file."""
        conference.track_mcp_client(ctx.client_id)
        content = file_manager.read_file(file_path)
        lock = file_manager.get_lock_info(file_path)
        return json.dumps({
            "file": file_path,
            "content": content,
            "lock": lock,
        })

    @mcp.tool()
    async def acquire_file_lock(agent_id: str, file_path: str, ctx: Context = None) -> str:
        """Acquire an exclusive write lock on a shared file.
        Blocks until the lock is available. Only the lock holder can write.
        Locks auto-expire after 3 minutes to prevent deadlock.
        Also blocks until the conference has been configured."""
        conference.track_mcp_client(ctx.client_id)
        await conference.wait_for_configuration()
        cond = _get_file_condition(file_path)
        async with cond:
            while not file_manager.acquire_lock(file_path, agent_id):
                try:
                    await asyncio.wait_for(cond.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    pass  # Retry — lock may have expired
        return json.dumps({"acquired": True, "file": file_path})

    @mcp.tool()
    async def release_file_lock(agent_id: str, file_path: str, ctx: Context = None) -> str:
        """Release your write lock on a shared file."""
        conference.track_mcp_client(ctx.client_id)
        file_manager.release_lock(file_path, agent_id)
        cond = _get_file_condition(file_path)
        async with cond:
            cond.notify_all()
        return json.dumps({"released": True, "file": file_path})

    @mcp.tool()
    async def write_shared_file(agent_id: str, file_path: str, content: str, ctx: Context = None) -> str:
        """Write to a shared file. You must hold the lock first (acquire_file_lock).
        This will block until the conference has been configured by the moderator."""
        conference.track_mcp_client(ctx.client_id)
        await conference.wait_for_configuration()
        file_manager.write_file(file_path, content, agent_id)
        return json.dumps({"status": "written", "file": file_path})

    # --- MCP Prompt ---

    @mcp.prompt()
    def conference_briefing(agent_id: str) -> str:
        """Get your full conference briefing: topic, goal, your role,
        other participants, and the round protocol."""
        return conference.get_briefing(agent_id)

    return {"mcp": mcp, "conference": conference, "file_manager": file_manager, "sessions_dir": sessions_dir}
