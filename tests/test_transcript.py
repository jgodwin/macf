import re
import json

import pytest
from pathlib import Path
from macf.models import (
    ConferenceState, ConferenceStatus, AgentInfo, AgentStatus,
    Message, Round, RoundStatus, RoundAction, ActionType,
    RoleConfig, ConferenceConfig,
)
from macf.transcript import generate_session_id, write_transcript, write_config
from macf.file_manager import FileManager


def _make_state():
    """Create a minimal completed conference state for testing."""
    state = ConferenceState(topic="Test Topic", goal="Test Goal")
    state.status = ConferenceStatus.COMPLETED

    # Add agents
    a1 = AgentInfo(name="Alice", role="Researcher")
    a2 = AgentInfo(name="Bob", role="Writer")
    state.agents[a1.id] = a1
    state.agents[a2.id] = a2

    # Round 1 with actions
    r1 = Round(number=1)
    r1.actions[a1.id] = RoundAction(agent_id=a1.id, type=ActionType.MESSAGE, content="Hello from Alice")
    r1.actions[a2.id] = RoundAction(agent_id=a2.id, type=ActionType.PASS)
    r1.status = RoundStatus.COMPLETED
    state.rounds.append(r1)

    # Round 2 with votes
    r2 = Round(number=2)
    r2.actions[a1.id] = RoundAction(agent_id=a1.id, type=ActionType.VOTE_TO_END)
    r2.actions[a2.id] = RoundAction(agent_id=a2.id, type=ActionType.VOTE_TO_END)
    r2.status = RoundStatus.COMPLETED
    state.rounds.append(r2)

    # Messages
    state.messages.append(Message(agent_id=a1.id, agent_name="Alice", round_number=1, content="Hello from Alice"))

    return state, a1, a2


def test_generate_session_id_format():
    """Session ID matches YYYYMMDD-HHMMSS-xxxxxxxx and timestamp comes from round start."""
    state, _, _ = _make_state()
    session_id = generate_session_id(state)

    pattern = r"^\d{8}-\d{6}-[0-9a-f]{8}$"
    assert re.match(pattern, session_id), f"Session ID '{session_id}' does not match expected format"

    # Verify timestamp portion comes from the first round's started_at
    ts_part = session_id[:15]  # YYYYMMDD-HHMMSS
    expected_ts = state.rounds[0].started_at.strftime("%Y%m%d-%H%M%S")
    assert ts_part == expected_ts

    # Verify the suffix is the first 8 chars of the state id
    suffix = session_id[16:]
    assert suffix == state.id[:8]


def test_generate_session_id_no_rounds():
    """State with no rounds still generates a valid session ID (uses current time)."""
    state = ConferenceState(topic="Empty")
    session_id = generate_session_id(state)

    pattern = r"^\d{8}-\d{6}-[0-9a-f]{8}$"
    assert re.match(pattern, session_id), f"Session ID '{session_id}' does not match expected format"
    assert session_id.endswith(state.id[:8])


def test_write_transcript_basic(tmp_path):
    """Write transcript and verify all expected content is present."""
    state, a1, a2 = _make_state()
    output = tmp_path / "transcript.md"
    result = write_transcript(state, output)

    assert result is True
    assert output.exists()

    content = output.read_text()

    # Topic and goal
    assert "Test Topic" in content
    assert "Test Goal" in content

    # Agent names
    assert "Alice" in content
    assert "Bob" in content

    # Agent roles
    assert "Researcher" in content
    assert "Writer" in content

    # Rounds
    assert "Round 1" in content
    assert "Round 2" in content

    # Message content
    assert "Hello from Alice" in content

    # Action types
    assert "message" in content
    assert "pass" in content
    assert "vote_to_end" in content


def test_write_transcript_skips_waiting(tmp_path):
    """State with WAITING status and no rounds should be skipped."""
    state = ConferenceState(topic="Waiting Conference")
    state.status = ConferenceStatus.WAITING
    output = tmp_path / "transcript.md"

    result = write_transcript(state, output)

    assert result is False
    assert not output.exists()


def test_write_transcript_skips_no_rounds(tmp_path):
    """State with ACTIVE status but empty rounds list should be skipped."""
    state = ConferenceState(topic="No Rounds")
    state.status = ConferenceStatus.ACTIVE
    output = tmp_path / "transcript.md"

    result = write_transcript(state, output)

    assert result is False
    assert not output.exists()


def test_write_transcript_halted(tmp_path):
    """State with HALTED status should produce a transcript containing 'halted'."""
    state = ConferenceState(topic="Halted Conference")
    state.status = ConferenceStatus.HALTED

    a1 = AgentInfo(name="Agent1", role="Tester")
    state.agents[a1.id] = a1

    r1 = Round(number=1)
    r1.actions[a1.id] = RoundAction(agent_id=a1.id, type=ActionType.MESSAGE, content="Before halt")
    r1.status = RoundStatus.COMPLETED
    state.rounds.append(r1)

    output = tmp_path / "transcript.md"
    result = write_transcript(state, output)

    assert result is True
    assert output.exists()

    content = output.read_text()
    assert "halted" in content


def test_write_transcript_creates_parent_dirs(tmp_path):
    """Transcript writing should auto-create parent directories."""
    state, _, _ = _make_state()
    output = tmp_path / "deep" / "nested" / "transcript.md"

    result = write_transcript(state, output)

    assert result is True
    assert output.exists()


def test_write_transcript_with_moderator(tmp_path):
    """Moderator messages should appear in the transcript."""
    state, a1, a2 = _make_state()

    # Add a moderator message for round 1
    mod_msg = Message(
        agent_id="moderator",
        agent_name="Moderator",
        round_number=1,
        content="Please stay on topic.",
    )
    state.messages.append(mod_msg)

    output = tmp_path / "transcript.md"
    result = write_transcript(state, output)

    assert result is True
    content = output.read_text()
    assert "Moderator" in content
    assert "Please stay on topic." in content


def test_file_manager_set_workspace(tmp_path):
    """set_workspace should switch directories and clear locks."""
    old_ws = tmp_path / "old_workspace"
    fm = FileManager(workspace_dir=old_ws)
    fm.create_file("test.txt", "old content")
    fm.acquire_lock("test.txt", "agent1")

    new_ws = tmp_path / "new_workspace"
    fm.set_workspace(new_ws)

    assert new_ws.exists()
    assert fm.workspace_dir == new_ws
    # Old files not in new workspace
    assert not (new_ws / "test.txt").exists()
    # Locks should be cleared — create file in new workspace and acquire lock
    fm.create_file("test.txt", "new content")
    assert fm.acquire_lock("test.txt", "agent2")


def test_write_config_basic(tmp_path):
    """Write a basic config and verify all fields are persisted correctly."""
    state = ConferenceState(topic="Test Topic", goal="Test Goal")
    roles = [
        RoleConfig(name="Architect", description="designs systems", instructions="Focus on structure"),
        RoleConfig(name="Developer", description="implements code", instructions="Follow best practices"),
    ]
    output = tmp_path / "config.json"

    result = write_config(state, roles, output)

    assert result is True
    assert output.exists()

    # Parse and verify the written config
    data = json.loads(output.read_text())
    assert data["topic"] == "Test Topic"
    assert data["goal"] == "Test Goal"
    assert len(data["roles"]) == 2
    assert data["roles"][0]["name"] == "Architect"
    assert data["roles"][0]["description"] == "designs systems"
    assert data["roles"][0]["instructions"] == "Focus on structure"
    assert data["roles"][1]["name"] == "Developer"
    assert data["roles"][1]["description"] == "implements code"
    assert data["roles"][1]["instructions"] == "Follow best practices"


def test_write_config_skips_empty_topic(tmp_path):
    """Config with empty topic should be skipped and file should not exist."""
    state = ConferenceState(topic="", goal="Test Goal")
    roles = [RoleConfig(name="TestRole", description="test", instructions="test")]
    output = tmp_path / "config.json"

    result = write_config(state, roles, output)

    assert result is False
    assert not output.exists()


def test_write_config_loadable_by_conference_config(tmp_path):
    """Written config should be loadable by ConferenceConfig.model_validate_json()."""
    state = ConferenceState(topic="Integration Test", goal="Verify Compatibility")
    roles = [
        RoleConfig(name="Analyst", description="analyzes data", instructions="Be thorough"),
        RoleConfig(name="Presenter", description="presents findings", instructions="Be clear"),
    ]
    output = tmp_path / "config.json"

    # Write the config
    result = write_config(state, roles, output)
    assert result is True

    # Load it back with ConferenceConfig
    json_content = output.read_text()
    loaded_config = ConferenceConfig.model_validate_json(json_content)

    # Verify all fields match
    assert loaded_config.topic == "Integration Test"
    assert loaded_config.goal == "Verify Compatibility"
    assert len(loaded_config.roles) == 2
    assert loaded_config.roles[0].name == "Analyst"
    assert loaded_config.roles[0].description == "analyzes data"
    assert loaded_config.roles[0].instructions == "Be thorough"
    assert loaded_config.roles[1].name == "Presenter"
    assert loaded_config.roles[1].description == "presents findings"
    assert loaded_config.roles[1].instructions == "Be clear"
