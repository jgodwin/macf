from __future__ import annotations

import json
import tempfile
from pathlib import Path
from mcp.server.fastmcp import FastMCP, Context

from macf2.conference import ConferenceManager
from macf2.file_manager import FileManager


def create_mcp_server(
    topic: str = "Untitled Conference",
    workspace_dir: Path | None = None,
) -> dict:
    """Create an MCP server wired to a conference and file manager.

    Returns a dict with keys: mcp, conference, file_manager.
    """
    if workspace_dir is None:
        workspace_dir = Path(tempfile.mkdtemp(prefix="macf2_"))

    conference = ConferenceManager(topic=topic)
    file_manager = FileManager(workspace_dir=workspace_dir)

    mcp = FastMCP(
        name="MACF2 Conference",
        instructions=(
            f"You are participating in a multi-agent conference on: {topic}. "
            "Use the provided tools to collaborate with other agents. "
            "Each round, you must either post a message, pass, or vote to end."
        ),
    )

    # --- Session-to-agent mapping ---
    _session_agents: dict[str, str] = {}  # client_id -> agent_id

    @mcp.tool()
    def register_agent(name: str, role: str = "") -> str:
        """Register yourself as a conference participant. Returns your agent_id.
        You must call this before any other action."""
        agent_id = conference.register_agent(name, role=role)
        return json.dumps({"agent_id": agent_id, "topic": conference.state.topic})

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
    def create_shared_file(file_path: str, content: str = "") -> str:
        """Create a new shared file that all agents can collaborate on."""
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

    @mcp.tool()
    def acquire_file_lock(agent_id: str, file_path: str) -> str:
        """Acquire an exclusive write lock on a shared file.
        Returns whether the lock was acquired. Only the lock holder can write."""
        acquired = file_manager.acquire_lock(file_path, agent_id)
        return json.dumps({"acquired": acquired, "file": file_path})

    @mcp.tool()
    def release_file_lock(agent_id: str, file_path: str) -> str:
        """Release your write lock on a shared file."""
        file_manager.release_lock(file_path, agent_id)
        return json.dumps({"released": True, "file": file_path})

    @mcp.tool()
    def write_shared_file(agent_id: str, file_path: str, content: str) -> str:
        """Write to a shared file. You must hold the lock first (acquire_file_lock)."""
        file_manager.write_file(file_path, content, agent_id)
        return json.dumps({"status": "written", "file": file_path})

    return {"mcp": mcp, "conference": conference, "file_manager": file_manager}
