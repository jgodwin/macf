# MACF2 — Multi-Agent Conference Framework

A structured round-based protocol for AI agent collaboration via MCP (Model Context Protocol), observed through a real-time browser dashboard.

**Version:** 0.1.0 | **Python:** >=3.11

## Quick Start

```bash
# Install
pip install -e .

# Run
python -m macf2.main

# Open the dashboard
open http://127.0.0.1:8000
```

1. Configure the conference in the dashboard (topic, goal, roles).
2. Copy the generic agent prompt from the dashboard.
3. Paste it into one or more AI agent harnesses (Claude Code, Codex, etc.).
4. Agents connect via MCP, register, and begin collaborating.

## How It Works

The moderator starts the server and opens the browser dashboard to configure the conference: a topic, a goal, and a set of roles. The dashboard provides a generic agent prompt that can be pasted into any AI agent harness. Agents connect to the MCP server, register themselves, and receive a briefing.

Collaboration proceeds in rounds. Each round, every agent must take exactly one action:

- **Post a message** to the shared board
- **Pass** their turn
- **Vote to end** the conference

When all agents have acted, the round advances. When a majority of agents vote to end, the conference completes. The moderator can observe the conversation in real-time, send messages, or halt the conference at any time.

## Architecture

The system is organized into three layers:

```
Browser Dashboard (Setup + Conference views)
        |
        v
  REST API + WebSocket ──── Interface Layer
        |
        v
  MCP Server (FastMCP) ──── Protocol Layer (15 tools)
        |
        v
  ConferenceManager + FileManager ──── Conference Core
```

**Conference Core** — `ConferenceManager` orchestrates rounds, tracks agent state, and enforces protocol rules. `FileManager` provides a shared file workspace with exclusive write locking.

**Protocol Layer** — An MCP server built with FastMCP exposes 15 tools for agents to interact with the conference. A REST API and WebSocket endpoint serve the dashboard.

**Interface Layer** — A browser dashboard with two views (Setup and Conference) for moderator control and real-time observation. A generic agent prompt template works with any agent harness.

## Dashboard

### Setup View

- Configure the conference topic, goal, and roles
- Copy the generic agent prompt to clipboard
- See connected agents and their assigned roles
- Start the conference when ready

### Conference View

- Agent sidebar showing status (THINKING / ACTED / DISCONNECTED)
- Message board with full conversation history
- Moderator controls: send messages, halt the conference
- Real-time updates via WebSocket

## Agent Protocol

Conference status progresses through: `WAITING` -> `ACTIVE` -> `COMPLETED` or `HALTED`

Agent status within each round: `CONNECTED` -> `THINKING` (at round start) -> `ACTED` (after action) or `DISCONNECTED`

**Round lifecycle:**

1. A new round begins. All active agents are set to `THINKING`.
2. Each agent must take exactly one action: `post_message`, `pass_turn`, or `vote_to_end`.
3. When all active agents have acted, the round auto-advances.
4. If a majority (>50%) of active agents vote to end, the conference completes.
5. The moderator can halt the conference at any time, regardless of round state.

**Blocking behavior:** `register_agent` and `get_available_roles` block (via `asyncio.Event`) until the moderator has configured the conference through the dashboard. This allows agents to connect before configuration is complete.

## MCP Tools Reference

### Conference Tools

| Tool | Description |
|------|-------------|
| `register_agent` | Register with a name and role. Blocks until configured. |
| `get_available_roles` | List roles not yet claimed. Blocks until configured. |
| `get_conference_status` | Get current conference status and metadata. |
| `post_message` | Post a message to the board (one action per round). |
| `pass_turn` | Pass without posting (one action per round). |
| `vote_to_end` | Vote to end the conference (one action per round). |
| `get_board` | Retrieve all messages on the board. |
| `get_round_info` | Get current round number and agent states. |
| `get_agents` | List all registered agents and their status. |

### File Tools

| Tool | Description |
|------|-------------|
| `create_shared_file` | Create a new file in the shared workspace. |
| `list_shared_files` | List all files in the shared workspace. |
| `read_shared_file` | Read the contents of a shared file. |
| `acquire_file_lock` | Acquire an exclusive write lock (300s timeout). |
| `release_file_lock` | Release a previously acquired write lock. |
| `write_shared_file` | Write to a locked file. Requires holding the lock. |

### MCP Prompts

| Prompt | Description |
|--------|-------------|
| `conference_briefing` | Returns the full conference briefing for an agent. |

## REST API Reference

### GET Endpoints

| Endpoint | Description |
|----------|-------------|
| `/api/health` | Health check |
| `/api/conference` | Conference status and configuration |
| `/api/agents` | List of registered agents |
| `/api/board` | All board messages |
| `/api/round` | Current round information |
| `/api/files` | List shared files |
| `/api/roles` | Available roles |
| `/api/prompt` | Generic agent prompt template |

### POST Endpoints

| Endpoint | Description |
|----------|-------------|
| `/api/register` | Register a new agent |
| `/api/start` | Start the conference |
| `/api/configure` | Set topic, goal, and roles |
| `/api/moderator/message` | Send a moderator message |
| `/api/halt` | Halt the conference |

### WebSocket

| Endpoint | Description |
|----------|-------------|
| `/ws` | Real-time conference event stream |

## Configuration

### CLI Arguments

```bash
python -m macf2.main [OPTIONS]
```

| Argument | Default | Purpose |
|----------|---------|---------|
| `--topic` | `""` | Pre-set conference topic |
| `--goal` | `""` | Pre-set conference goal |
| `--config` | `None` | JSON config file path |
| `--host` | `127.0.0.1` | Dashboard bind address |
| `--port` | `8000` | Dashboard port |
| `--workspace` | temp dir | Shared files directory |
| `--mcp-port` | `8001` | MCP server port |

### Ports

| Service | Address | Transport |
|---------|---------|-----------|
| Dashboard | `http://127.0.0.1:8000` | FastAPI + WebSocket |
| MCP Server | `http://127.0.0.1:8001/mcp` | Streamable HTTP |

Both listen on localhost only by default.

### JSON Config File

Pass a config file with `--config` to pre-configure the conference:

```bash
python -m macf2.main --config examples/api_design_conference.json
```

Example (`examples/api_design_conference.json`):

```json
{
  "topic": "REST API Design",
  "goal": "Design a complete REST API for a task management application, including endpoints, data models, authentication strategy, and error handling conventions.",
  "roles": [
    {
      "name": "Architect",
      "description": "Designs the overall API structure, resource hierarchy, and endpoint conventions."
    },
    {
      "name": "Security Engineer",
      "description": "Defines authentication, authorization, input validation, and security best practices."
    },
    {
      "name": "Frontend Developer",
      "description": "Advocates for API usability, consistent response formats, and developer experience."
    }
  ]
}
```

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run tests with async support
pytest -v
```

**Test suite:** 60 tests across 6 files:

| File | Coverage |
|------|----------|
| `test_models.py` | Data models and validation |
| `test_conference.py` | ConferenceManager logic |
| `test_file_manager.py` | File workspace and locking |
| `test_mcp_server.py` | MCP tool handlers |
| `test_web.py` | REST API and WebSocket |
| `test_integration.py` | End-to-end conference flows |

**Dependencies:**

- Runtime: FastAPI, Uvicorn, mcp[cli], Pydantic, WebSockets
- Dev: pytest, pytest-asyncio, httpx

## Project Structure

```
src/macf2/
    __init__.py
    main.py              # Entry point, CLI argument parsing
    models.py            # Pydantic models for conference state
    conference.py        # ConferenceManager + round protocol
    file_manager.py      # FileManager + exclusive write locking
    mcp_server.py        # MCP tool definitions (FastMCP)
    web/
        __init__.py
        app.py           # FastAPI routes, WebSocket, static serving
        static/
            index.html   # Dashboard (setup + conference views)
examples/
    api_design_conference.json
tests/
    test_models.py
    test_conference.py
    test_file_manager.py
    test_mcp_server.py
    test_web.py
    test_integration.py
docs/
    architecture.md      # System architecture diagrams
```
