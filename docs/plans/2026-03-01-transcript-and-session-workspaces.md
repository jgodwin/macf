# Transcript Writing + Session-Based Workspaces

## Context

Currently there's no record of what agents said/did after a conference ends, and the workspace is a single shared `./workspace/` folder that bleeds across conversations. The user wants:

1. **Full transcript** — Markdown file written at conference end with all messages and actions attributed by agent ID and role, saved per-session.
2. **Session-based workspaces** — Each conversation gets its own workspace folder identified by a timestamp+ID, so files don't bleed across sessions.

## Architecture

```
sessions/
  20260301-143022-a1b2c3d4/
    workspace/
      shared_file.txt
    transcript.md
  20260301-151045-e5f6g7h8/
    workspace/
      ...
    transcript.md
```

- **Session ID format**: `YYYYMMDD-HHMMSS-<first 8 chars of ConferenceState.id>`
- **Sessions base dir**: `./sessions/` (relative to cwd, configurable via --sessions-dir CLI arg)
- Each session directory contains `workspace/` for agent files and `transcript.md` for the conference record

## Files to Create

- `src/macf2/transcript.py` — Transcript generation logic
- `tests/test_transcript.py` — Tests for transcript output

## Files to Modify

- `src/macf2/conference.py` — Pass old state in `conference_reset` event so transcript can be written before state is lost
- `src/macf2/mcp_server.py` — Use session-based workspace path, expose method to update workspace on reset
- `src/macf2/web/app.py` — Wire transcript writing on conference end/halt/reset, create new session workspace on reset
- `src/macf2/file_manager.py` — Add `set_workspace()` method to switch workspace directory on reset
- `src/macf2/main.py` — Add `--sessions-dir` CLI argument, pass to create_app

---

## Task 1: Create `transcript.py` module

### 1a. `generate_session_id(state)` function

Takes a `ConferenceState`, returns formatted string like `20260301-143022-a1b2c3d4`:
- Timestamp from `state.rounds[0].started_at` if rounds exist, else `datetime.now(timezone.utc)`
- First 8 chars of `state.id`

### 1b. `write_transcript(state, output_path)` function

Takes a `ConferenceState` and a `Path`, writes a markdown transcript. Format:

```markdown
# Conference Transcript

**Topic:** {topic}
**Goal:** {goal}
**Status:** {status}
**Session ID:** {state.id}
**Started:** {timestamp}
**Ended:** {timestamp}

## Participants

| Agent ID | Name | Role |
|----------|------|------|
| abc123   | Alice | Researcher |
| def456   | Bob   | Writer     |

## Round 1

### Alice (abc123) — message
{content}

### Bob (def456) — pass

---

## Round 2

### Alice (abc123) — message
{content}

### Bob (def456) — vote_to_end

---

## Summary

- Total rounds: 3
- Total messages: 5
- Outcome: completed (majority_vote)
```

Logic:
- Header section from `state.topic`, `state.goal`, `state.status`, timestamps from first/last round
- Participants table from `state.agents` (id, name, role)
- Per-round sections: iterate `state.rounds`, for each round iterate its `actions` dict. For MESSAGE actions, include the content (looked up from `state.messages` by matching agent_id and round_number). For PASS and VOTE_TO_END, just note the action type.
- Summary with counts

### 1c. Guard against empty conferences

If `state.status == WAITING` or no rounds exist, skip writing (nothing to record).

---

## Task 2: Session-based workspace directories

### 2a. Add `set_workspace()` to `FileManager`

Add method to `file_manager.py`:
```python
def set_workspace(self, workspace_dir: Path) -> None:
    self.workspace_dir = workspace_dir
    self.workspace_dir.mkdir(parents=True, exist_ok=True)
    self._locks = {}  # Clear locks for new session
```

### 2b. Modify `create_mcp_server()` to use session-based workspace

In `mcp_server.py`, change default workspace logic:
- Accept `sessions_dir: Path | None` parameter (default `Path.cwd() / "sessions"`)
- Generate session directory from `conference.state.id` using `generate_session_id()`
- Set workspace to `sessions_dir / session_id / "workspace"`
- Store `sessions_dir` for later use on reset

### 2c. Update `main.py` CLI

- Add `--sessions-dir` argument (default: None → becomes `./sessions/`)
- Pass through to `create_app()`

### 2d. Update `create_app()` signature

Accept `sessions_dir` parameter, pass to `create_mcp_server()`.

---

## Task 3: Wire transcript writing into app lifecycle

### 3a. Register transcript event listener in `app.py`

After creating conference and file_manager, register an event listener:
```python
async def on_transcript_event(event_type: str, data: dict) -> None:
    if event_type in ("conference_ended", "conference_halted"):
        session_id = generate_session_id(conference.state)
        session_dir = sessions_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        write_transcript(conference.state, session_dir / "transcript.md")
```

### 3b. Handle reset — write transcript then create new session

Modify `conference.reset()` to include old state in the `conference_reset` event:
```python
def reset(self) -> None:
    old_state = self.state
    self.state = ConferenceState(topic="", goal="")
    self._roles = []
    self._configured = asyncio.Event()
    self._turn_order = []
    self._current_turn_index = 0
    self._emit("conference_reset", {"old_state": old_state})
```

In `app.py`, handle the reset event:
```python
if event_type == "conference_reset":
    old_state = data.get("old_state")
    if old_state and old_state.rounds:
        old_session_id = generate_session_id(old_state)
        old_session_dir = sessions_dir / old_session_id
        old_session_dir.mkdir(parents=True, exist_ok=True)
        write_transcript(old_state, old_session_dir / "transcript.md")
    # Create new session workspace
    new_session_id = generate_session_id(conference.state)
    new_session_dir = sessions_dir / new_session_id
    file_manager.set_workspace(new_session_dir / "workspace")
```

### 3c. Print session directory at startup

In `main.py` or `create_mcp_server()`, print the session directory path so the user knows where files are being saved.

---

## Task 4: Tests

### 4a. Test transcript generation

- `test_write_transcript_basic` — 2 agents, 2 rounds, verify markdown contains topic, goal, agent names/IDs/roles, round headers, message content, action types
- `test_write_transcript_with_moderator_messages` — verify moderator messages appear
- `test_write_transcript_skips_empty` — no rounds → no transcript written
- `test_write_transcript_halted` — halted conference gets transcript with halted status

### 4b. Test session ID generation

- `test_generate_session_id_format` — verify format matches `YYYYMMDD-HHMMSS-xxxxxxxx`
- `test_generate_session_id_uses_round_start` — verify timestamp comes from first round's started_at

### 4c. Test set_workspace

- `test_file_manager_set_workspace` — verify workspace changes and directory is created

---

## Verification

1. `source .venv/bin/activate && python -m pytest tests/ --tb=short` — all tests pass
2. Start server, run a conference, verify transcript.md is written to `sessions/<id>/transcript.md`
3. Verify workspace files are in `sessions/<id>/workspace/`
4. Reset and verify new session directory is created, old transcript preserved
