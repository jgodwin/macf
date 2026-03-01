# MACF2 Architecture

**Multi-Agent Conference Framework 2 -- System Architecture**

This document describes the architecture of MACF2 using plain ASCII diagrams
that render in any terminal, editor, or markdown viewer.

---

## 1. System Overview

MACF2 has three actor classes: a human **Moderator** using a browser dashboard,
a set of **AI Agents** that connect via the Model Context Protocol (MCP), and
the **server** that hosts both the dashboard and MCP endpoint. The dashboard
(FastAPI on port 8000) and the MCP server (FastMCP on port 8001) share the same
in-process `ConferenceManager` and `FileManager` singletons, so every mutation
an agent makes is immediately visible to the moderator and vice-versa.

```
                         ┌──────────────────┐
                         │    Moderator     │
                         │    (Browser)     │
                         └────────┬─────────┘
                                  │
                         HTTP + WebSocket
                                  │
                         ┌────────▼─────────┐
                         │    Dashboard     │
                         │  FastAPI :8000   │
                         │  ┌────────────┐  │
                         │  │  REST API  │  │
                         │  │  WebSocket │  │
                         │  └────────────┘  │
                         └────────┬─────────┘
                                  │
                                  │  Shared Python objects (in-process)
                                  │
               ┌──────────────────┼──────────────────┐
               │                  │                  │
     ┌─────────▼────────┐  ┌─────▼──────┐  ┌────────▼─────────┐
     │  Conference       │  │   Event    │  │  File             │
     │  Manager          │  │   Bus      │  │  Manager          │
     │  (state machine)  │  │            │  │  (async locking)  │
     └─────────▲────────┘  └─────▲──────┘  └────────▲─────────┘
               │                  │                  │
               └──────────────────┼──────────────────┘
                                  │
                                  │  Shared Python objects (in-process)
                                  │
                         ┌────────▼─────────┐
                         │   MCP Server     │
                         │  FastMCP :8001   │
                         │  ┌────────────┐  │
                         │  │  15 Tools  │  │
                         │  │  1 Prompt  │  │
                         │  └────────────┘  │
                         └────────┬─────────┘
                                  │
                         Streamable HTTP (MCP protocol)
                                  │
               ┌──────────────────┼──────────────────┐
               │                  │                  │
         ┌─────▼─────┐     ┌─────▼─────┐     ┌─────▼─────┐
         │  Agent 1  │     │  Agent 2  │     │  Agent N  │
         │ (Claude)  │     │  (Codex)  │     │   (any)   │
         └───────────┘     └───────────┘     └───────────┘
```

**Key points:**

- The Dashboard and MCP Server run in the same Python process, started by
  `main.py`. They share references to the same `ConferenceManager` and
  `FileManager` instances -- no IPC or serialization needed.
- The Event Bus is a lightweight async callback registry inside
  `ConferenceManager`. When state changes (agent joins, message posted, round
  advances), an event fires and the Dashboard's WebSocket handler broadcasts
  the update to every connected browser.
- Agents are external processes. They can be any LLM or program that speaks
  MCP over Streamable HTTP. They discover available tools on connection and
  use them to participate in the conference.

---

## 2. Conference Lifecycle / State Machine

A conference progresses through a linear state machine with one branch for
moderator-initiated halts.

```
  ┌───────────────────────────────────────────────────────────────────┐
  │                   Conference State Machine                        │
  └───────────────────────────────────────────────────────────────────┘

       configure()           start()             (majority vote
       set topic,            begin round 1        OR all rounds
       goal, roles                                exhausted)
           │                     │                     │
           │                     │                     │
     ┌─────▼─────┐        ┌─────▼─────┐        ┌──────▼──────┐
     │           │        │           │        │             │
     │  WAITING  ├───────►│  ACTIVE   ├───────►│  COMPLETED  │
     │           │        │           │        │             │
     └───────────┘        └─────┬─────┘        └─────────────┘
                                │
                           halt()
                           (moderator)
                                │
                          ┌─────▼─────┐
                          │           │
                          │  HALTED   │
                          │           │
                          └───────────┘
```

### State descriptions

| State       | What happens                                                      |
|-------------|-------------------------------------------------------------------|
| `WAITING`   | Moderator configures the conference: sets topic, goal, and roles. |
|             | Agents connect and call `register_agent` to join. Agents that     |
|             | try to act before configuration is complete are blocked.          |
| `ACTIVE`    | Rounds are in progress. Each round, every agent gets one action.  |
|             | The round auto-advances when all agents have acted.               |
| `COMPLETED` | A majority of agents voted to end the conference, or the maximum  |
|             | round count was reached. The conference is read-only.             |
| `HALTED`    | The moderator manually halted the conference via the dashboard.   |
|             | Equivalent to COMPLETED but initiated by a human.                 |

### Transitions

```
  WAITING ──(configure_conference)──► WAITING   [topic/goal/roles updated]
  WAITING ──(register_agent)────────► WAITING   [agent added to roster]
  WAITING ──(start_conference)──────► ACTIVE    [round 1 begins]
  ACTIVE  ──(round completes)───────► ACTIVE    [next round begins]
  ACTIVE  ──(majority vote_to_end)──► COMPLETED [conference ends normally]
  ACTIVE  ──(max rounds reached)────► COMPLETED [conference ends normally]
  ACTIVE  ──(halt_conference)───────► HALTED    [moderator stops conference]
```

---

## 3. Round Flow

Each round follows a strict turn protocol. All registered agents must act
exactly once before the round advances.

```
  ┌─────────────────────────────────────────────────────────────────┐
  │                       Round N Begins                            │
  │         All agents set to status: THINKING                      │
  └──────────────────────────┬──────────────────────────────────────┘
                             │
                             ▼
            ┌────────────────────────────────┐
            │  Agent picks one action:       │
            │                                │
            │   ┌──────────────────────┐     │
            │   │  post_message        │     │  Posts a message to the
            │   │  (content, msg_type) │     │  conference transcript
            │   └──────────────────────┘     │
            │                                │
            │   ┌──────────────────────┐     │
            │   │  pass_turn           │     │  Skips this round
            │   │  ()                  │     │  (nothing to add)
            │   └──────────────────────┘     │
            │                                │
            │   ┌──────────────────────┐     │
            │   │  vote_to_end         │     │  Casts a vote to end
            │   │  (reason)            │     │  the conference
            │   └──────────────────────┘     │
            │                                │
            │  Agent status ──► ACTED        │
            └────────────────┬───────────────┘
                             │
                             ▼
            ┌────────────────────────────────┐
            │  All agents acted this round?  │
            │                                │
            │    NO ──► wait for remaining   │
            │                                │
            │    YES ──► evaluate votes      │
            └────────────────┬───────────────┘
                             │
                             ▼
            ┌────────────────────────────────┐
            │  Majority voted to end?        │
            │                                │
            │    YES ──► state = COMPLETED   │
            │                                │
            │    NO  ──► Round N+1 begins    │
            │            (reset all agents   │
            │             to THINKING)       │
            └────────────────────────────────┘
```

### Agent status within a round

```
  THINKING ──(post_message)──► ACTED
  THINKING ──(pass_turn)─────► ACTED
  THINKING ──(vote_to_end)───► ACTED
```

An agent can only act once per round. Attempting a second action while in
`ACTED` status returns an error.

---

## 4. Data Flow Diagram

This shows the complete path of a typical agent action, from tool call to
dashboard update.

```
  ┌───────────┐    MCP tool call     ┌──────────────┐
  │           │  (Streamable HTTP)   │              │
  │   Agent   ├─────────────────────►│  MCP Server  │
  │           │                      │  (FastMCP)   │
  └───────────┘                      └──────┬───────┘
                                            │
                                   calls method on
                                   shared instance
                                            │
                                     ┌──────▼───────────┐
                                     │                  │
                                     │  Conference      │
                                     │  Manager         │
                                     │                  │
                                     │  1. Validate     │
                                     │  2. Mutate state │
                                     │  3. Emit event   │
                                     │                  │
                                     └──────┬───────────┘
                                            │
                                       event fires
                                            │
                                     ┌──────▼───────────┐
                                     │                  │
                                     │  Event Bus       │
                                     │  (callbacks)     │
                                     │                  │
                                     └──────┬───────────┘
                                            │
                                    WebSocket broadcast
                                            │
                                     ┌──────▼───────────┐
                                     │                  │
                                     │  Dashboard       │
                                     │  WebSocket       │
                                     │  Handler         │
                                     │                  │
                                     └──────┬───────────┘
                                            │
                                      JSON message
                                            │
                                     ┌──────▼───────────┐
                                     │                  │
                                     │  Browser         │
                                     │  (Moderator)     │
                                     │                  │
                                     │  JS updates DOM  │
                                     │                  │
                                     └──────────────────┘
```

### Example: `post_message` tool call

```
  1. Agent calls post_message(agent_id, content, message_type)
                           │
  2. MCP Server resolves   │   the tool, invokes handler
                           │
  3. Handler calls         │   conference_manager.post_message(...)
                           │
  4. ConferenceManager     │   validates:
     - Is conference       │   ACTIVE?
     - Is it this agent's  │   turn (status == THINKING)?
     - Is content valid?   │
                           │
  5. On success:           │
     - Message appended    │   to transcript
     - Agent status ──►    │   ACTED
     - Event emitted:      │   {"type": "message_posted", ...}
                           │
  6. Event handler in      │   web/app.py sends JSON over WebSocket
                           │
  7. Browser JS receives   │   event, updates transcript panel
                           │
  8. Tool returns success  │   result to agent via MCP response
```

---

## 5. File Locking Flow

The `FileManager` provides a cooperative locking mechanism so multiple agents
can safely collaborate on shared files (e.g., a design document, code artifact).

### Happy path

```
  Agent A                        FileManager                    Storage
  ───────                        ───────────                    ───────
     │                                │                            │
     │  acquire_lock(file, agent_a)   │                            │
     ├───────────────────────────────►│                            │
     │                                │  lock table:               │
     │                                │  file ──► agent_a          │
     │           lock_acquired        │                            │
     │◄───────────────────────────────┤                            │
     │                                │                            │
     │  write_file(file, content)     │                            │
     ├───────────────────────────────►│                            │
     │                                │  verify lock owner         │
     │                                ├───────────────────────────►│
     │                                │         write to disk      │
     │           write_success        │                            │
     │◄───────────────────────────────┤                            │
     │                                │                            │
     │  release_lock(file, agent_a)   │                            │
     ├───────────────────────────────►│                            │
     │                                │  lock table:               │
     │                                │  file ──► (removed)        │
     │           lock_released        │                            │
     │◄───────────────────────────────┤                            │
     │                                │                            │
```

### Conflict case

```
  Agent A                        FileManager                  Agent B
  ───────                        ───────────                  ───────
     │                                │                          │
     │  acquire_lock(file, agent_a)   │                          │
     ├───────────────────────────────►│                          │
     │           lock_acquired        │                          │
     │◄───────────────────────────────┤                          │
     │                                │                          │
     │                                │  acquire_lock(file,      │
     │                                │               agent_b)   │
     │                                │◄─────────────────────────┤
     │                                │                          │
     │                                │  lock table says:        │
     │                                │  file ──► agent_a        │
     │                                │                          │
     │                                │  ERROR: file locked      │
     │                                │  by agent_a              │
     │                                ├─────────────────────────►│
     │                                │                          │
     │  release_lock(file, agent_a)   │                          │
     ├───────────────────────────────►│                          │
     │           lock_released        │                          │
     │◄───────────────────────────────┤                          │
     │                                │                          │
     │                                │  acquire_lock(file,      │
     │                                │               agent_b)   │
     │                                │◄─────────────────────────┤
     │                                │  lock_acquired           │
     │                                ├─────────────────────────►│
     │                                │                          │
```

### Write validation

```
  Agent C                        FileManager
  ───────                        ───────────
     │                                │
     │  write_file(file, content)     │
     ├───────────────────────────────►│
     │                                │
     │                                │  Is file locked by Agent C?
     │                                │  YES ──► proceed with write
     │                                │  NO  ──► ERROR: must hold lock
     │                                │
```

Agents must acquire a lock before writing. Writing without a lock or
with someone else's lock raises an error.

---

## 6. Project Structure

```
  macf2/
  │
  ├── src/macf2/                       # Main package
  │   ├── __init__.py                  # Package init, version
  │   ├── main.py                      # CLI entry point (argparse)
  │   │                                #   - parses args
  │   │                                #   - creates ConferenceManager, FileManager
  │   │                                #   - starts both servers
  │   │
  │   ├── models.py                    # Pydantic data models
  │   │                                #   - ConferenceState enum
  │   │                                #   - AgentStatus enum
  │   │                                #   - Agent, Message, Round
  │   │                                #   - Conference, FileInfo, FileLock
  │   │
  │   ├── conference.py                # ConferenceManager
  │   │                                #   - state machine logic
  │   │                                #   - round management
  │   │                                #   - vote counting
  │   │                                #   - event emission
  │   │
  │   ├── file_manager.py              # FileManager
  │   │                                #   - file read/write
  │   │                                #   - lock acquire/release
  │   │                                #   - conflict detection
  │   │
  │   ├── mcp_server.py                # MCP tools factory
  │   │                                #   - 15 tool definitions
  │   │                                #   - 1 prompt (system prompt for agents)
  │   │                                #   - tool handlers delegate to managers
  │   │
  │   └── web/                         # Dashboard package
  │       ├── __init__.py
  │       ├── app.py                   # FastAPI application
  │       │                            #   - REST endpoints
  │       │                            #   - WebSocket endpoint
  │       │                            #   - event subscription
  │       │
  │       └── static/
  │           └── index.html           # Single-page dashboard UI
  │                                    #   - vanilla JS (no framework)
  │                                    #   - WebSocket client
  │                                    #   - real-time transcript view
  │                                    #   - moderator controls
  │
  ├── tests/                           # Test suite
  │   ├── test_models.py               # Model validation tests
  │   ├── test_conference.py           # ConferenceManager unit tests
  │   ├── test_file_manager.py         # FileManager unit tests
  │   ├── test_mcp_server.py           # MCP tool tests
  │   ├── test_web.py                  # Dashboard/API tests
  │   └── test_integration.py          # End-to-end flow tests
  │
  ├── examples/
  │   └── api_design_conference.json   # Sample conference configuration
  │
  ├── docs/
  │   ├── architecture.md              # This file
  │   └── plans/                       # Design documents
  │
  └── pyproject.toml                   # Project metadata, dependencies
                                       #   - fastapi, uvicorn
                                       #   - fastmcp
                                       #   - pydantic
                                       #   - websockets
```

---

## 7. MCP Tool Inventory

For reference, the 15 tools exposed by the MCP server, grouped by function:

```
  ┌──────────────────────────────────────────────────────────────────┐
  │                        MCP Tools (15)                            │
  ├──────────────────┬───────────────────┬───────────────────────────┤
  │  Conference         │  Agent Actions  │  File Operations          │
  │  Management         │  (per-round)   │                           │
  ├──────────────────── ┼────────────────┼───────────────────────────┤
  │                     │                │                           │
  │  register_agent *   │  post_message  │  create_shared_file       │
  │  get_available      │  pass_turn     │  list_shared_files        │
  │    _roles *         │  vote_to_end   │  read_shared_file         │
  │  get_conference     │                │  acquire_file_lock        │
  │    _status          │                │  release_file_lock        │
  │  get_board          │                │  write_shared_file        │
  │  get_round_info     │                │                           │
  │  get_agents         │                │  * = blocks until         │
  │                     │                │    configured             │
  └──────────────────┴───────────────────┴───────────────────────────┘

  ┌──────────────────────────────────────────────────────────────────┐
  │                        MCP Prompts (1)                           │
  ├──────────────────────────────────────────────────────────────────┤
  │                                                                  │
  │  conference_briefing                                             │
  │    Returns the full conference briefing for an agent:            │
  │    topic, goal, role, other participants, and round protocol.    │
  │                                                                  │
  └──────────────────────────────────────────────────────────────────┘
```

---

## 8. Deployment Topology

A single `macf2` process hosts everything. No external databases or message
brokers are required.

```
  ┌─────────────────────────────────────────────────────────────┐
  │                                                             │
  │                  macf2 process (Python)                      │
  │                                                             │
  │   ┌───────────────────────┐  ┌───────────────────────────┐  │
  │   │  Uvicorn server #1   │  │  Uvicorn server #2        │  │
  │   │  :8000               │  │  :8001                    │  │
  │   │                      │  │                           │  │
  │   │  FastAPI app         │  │  FastMCP app              │  │
  │   │  (Dashboard)         │  │  (MCP Server)             │  │
  │   └──────────┬───────────┘  └──────────┬────────────────┘  │
  │              │                         │                   │
  │              │    ┌────────────────┐    │                   │
  │              └───►│ Conference     │◄───┘                   │
  │                   │ Manager       │                         │
  │                   ├────────────────┤                         │
  │                   │ File          │                         │
  │                   │ Manager       │                         │
  │                   └────────────────┘                         │
  │                                                             │
  │   In-memory state, no external dependencies                 │
  │                                                             │
  └─────────────────────────────────────────────────────────────┘

       :8000                                   :8001
         │                                       │
    ┌────▼────┐                          ┌───────▼───────┐
    │ Browser │                          │  AI Agents    │
    │ (human) │                          │  (N clients)  │
    └─────────┘                          └───────────────┘
```

---

*Generated for MACF2 -- Multi-Agent Conference Framework 2*
