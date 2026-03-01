# MACF Architecture

**Multi-Agent Conference Framework 2 -- Technical Reference**

This document describes the internal architecture of MACF using ASCII art
diagrams. Every fact is drawn from the actual source code.

---

## 1. System Overview

MACF runs as a single Python process hosting two HTTP servers on separate
ports. The dashboard server (FastAPI on port 8000) serves the browser UI, a
REST API, and a WebSocket endpoint. The MCP server (FastMCP on port 8001)
exposes 15 tools and 1 prompt to AI agents via Streamable HTTP. Both servers
share the same in-process `ConferenceManager` and `FileManager` instances --
no IPC, no database, no message broker.

```
 ┌─────────────────────────────────────────────────────────────────────┐
 │                     macf process (Python)                          │
 │                                                                     │
 │  Main Thread                          Daemon Thread                 │
 │  ┌────────────────────────┐           ┌─────────────────────────┐   │
 │  │  Uvicorn :8000         │           │  Uvicorn :8001          │   │
 │  │  ┌──────────────────┐  │           │  ┌───────────────────┐  │   │
 │  │  │  FastAPI          │  │           │  │  FastMCP          │  │   │
 │  │  │  ├─ GET /         │  │           │  │  ├─ 15 MCP tools  │  │   │
 │  │  │  │  (dashboard)   │  │           │  │  └─ 1 MCP prompt  │  │   │
 │  │  │  ├─ /api/*        │  │           │  └───────────────────┘  │   │
 │  │  │  │  (REST API)    │  │           │  Streamable HTTP /mcp   │   │
 │  │  │  └─ /ws           │  │           └────────────┬────────────┘   │
 │  │  │     (WebSocket)   │  │                        │                │
 │  │  └──────────────────┘  │                        │                │
 │  └───────────┬────────────┘                        │                │
 │              │                                     │                │
 │              │  ┌───────────────────────────────┐   │                │
 │              └─►│  ConferenceManager            │◄──┘                │
 │                 │  (state machine, events,      │                    │
 │                 │   round-robin protocol)       │                    │
 │                 ├───────────────────────────────┤                    │
 │                 │  FileManager                  │                    │
 │                 │  (locking, path traversal     │                    │
 │                 │   protection, workspace I/O)  │                    │
 │                 └───────────────────────────────┘                    │
 │                  Shared in-process Python objects                    │
 └─────────────────────────────────────────────────────────────────────┘
        │                                              │
   HTTP + WebSocket                          Streamable HTTP (MCP)
        │                                              │
 ┌──────▼──────┐                    ┌──────────────────▼──────────────┐
 │   Browser   │                    │          AI Agents              │
 │ (Moderator) │                    │  ┌─────┐  ┌─────┐     ┌─────┐  │
 └─────────────┘                    │  │  1  │  │  2  │ ... │  N  │  │
                                    │  └─────┘  └─────┘     └─────┘  │
                                    └─────────────────────────────────┘
```

---

## 2. Conference State Machine

A conference has four states. Transitions are driven by moderator actions
(configure, start, halt, reset) and agent voting. The `start()` method
requires at least 2 registered agents and a configured topic. The `reset()`
method can be called from any state and creates a brand-new session.

```
                       start()
                       (requires >=2 agents
                        + topic configured)
                            │
  ┌───────────┐             │            ┌─────────────┐
  │           ├─────────────┴───────────►│             │
  │  WAITING  │                          │   ACTIVE    │
  │           │◄─────────────────────────┤             │
  └───────────┘     reset()              └──────┬──┬───┘
       ▲            (from any state)            │  │
       │                                        │  │
       │  reset()                               │  │  halt()
       │  (from any state)                      │  │  (moderator)
       │                                        │  │
       │         ┌──────────────┐               │  │  ┌──────────┐
       ├─────────┤  COMPLETED   │◄──────────────┘  └─►│  HALTED  │
       │         └──────────────┘  majority            └──────────┘
       │                           vote_to_end              │
       │                           in a round               │
       └────────────────────────────────────────────────────┘
                              reset()
```

### Transition Table

```
  From      Trigger                       To          Notes
  ────      ───────                       ──          ─────
  WAITING   configure()                   WAITING     Sets topic/goal/roles
  WAITING   register_agent()              WAITING     Adds agent to roster
  WAITING   start()                       ACTIVE      Round 1 begins
  ACTIVE    round completes, no majority  ACTIVE      Next round begins
  ACTIVE    majority vote_to_end          COMPLETED   Conference ends normally
  ACTIVE    halt()                        HALTED      Moderator stops conference
  Any       reset()                       WAITING     New session created
```

---

## 3. Round Lifecycle

Each round requires every active agent to take exactly one action (post a
message, pass, or vote to end). Round 1 is parallel: all agents are set to
THINKING simultaneously and may act in any order. Round 2+ uses round-robin:
only one agent is set to THINKING at a time, and the rest wait.

```
  Round 1 (Parallel)                   Round 2+ (Round-Robin)
  ──────────────────                   ──────────────────────

  ┌──────────────────────┐             ┌──────────────────────────────┐
  │ All agents set to    │             │ Agent 1 set to THINKING      │
  │ THINKING at once     │             │ (others stay CONNECTED)      │
  ├──────────────────────┤             ├──────────────────────────────┤
  │                      │             │ Agent 1 acts                 │
  │ Agents act in any    │             │   → Agent 1 status = ACTED  │
  │ order. Each agent    │             │   → Agent 2 set to THINKING │
  │ calls one of:        │             │                              │
  │   - post_message     │             │ Agent 2 acts                 │
  │   - pass_turn        │             │   → Agent 2 status = ACTED  │
  │   - vote_to_end      │             │   → Agent 3 set to THINKING │
  │                      │             │                              │
  │ Agent status → ACTED │             │ Agent 3 acts                 │
  │ after each action    │             │   → Agent 3 status = ACTED  │
  ├──────────────────────┤             ├──────────────────────────────┤
  │ All acted?           │             │ All acted?                   │
  │  NO  → wait          │             │  YES → check votes           │
  │  YES → check votes   │             └──────────────┬───────────────┘
  └──────────┬───────────┘                            │
             │                                        │
             ▼                                        ▼
  ┌──────────────────────────────────────────────────────────────┐
  │  Majority voted to end?                                      │
  │    YES → conference status = COMPLETED                       │
  │    NO  → start next round (reset agents, advance round #)   │
  └──────────────────────────────────────────────────────────────┘
```

### Agent Status Within a Round

```
  THINKING ──(post_message)──► ACTED
  THINKING ──(pass_turn)─────► ACTED
  THINKING ──(vote_to_end)───► ACTED
```

An agent can only act once per round. A second attempt returns an error.
In round-robin mode, acting out of turn also returns an error.

---

## 4. Event and Data Flow

When an agent calls an MCP tool, the request flows through the MCP server
into the shared ConferenceManager, which validates the action, mutates
state, and emits an event. Two listeners handle events: one broadcasts to
the browser via WebSocket, the other writes transcripts on end/halt/reset.

```
  ┌─────────┐   Streamable HTTP    ┌─────────────┐
  │  Agent   ├─────────────────────►│  MCP Server │
  └─────────┘   POST /mcp          │  (FastMCP)  │
                                    └──────┬──────┘
                                           │
                                    calls method on
                                    shared instance
                                           │
                                    ┌──────▼──────────────────────────────┐
                                    │  ConferenceManager._record_action() │
                                    │                                     │
                                    │  1. Validate state (ACTIVE?)        │
                                    │  2. Validate turn (THINKING?)       │
                                    │  3. Record action in round          │
                                    │  4. Set agent status → ACTED        │
                                    │  5. _emit("agent_acted", data)      │
                                    └──────┬──────────────────────────────┘
                                           │
                              event fires to all listeners
                                           │
                      ┌────────────────────┼────────────────────┐
                      │                                         │
               ┌──────▼─────────┐                    ┌──────────▼──────────┐
               │ on_conference   │                    │ on_transcript       │
               │ _event()        │                    │ _event()            │
               │                 │                    │                     │
               │ WebSocket       │                    │ On end/halt/reset:  │
               │ broadcast to    │                    │ write_transcript()  │
               │ all connected   │                    │ to session dir      │
               │ browsers        │                    │                     │
               └──────┬──────────┘                    └─────────────────────┘
                      │
               JSON over WebSocket
                      │
               ┌──────▼──────┐
               │   Browser   │
               │ JS updates  │
               │ DOM in      │
               │ real time   │
               └─────────────┘
```

### Event Types Emitted by ConferenceManager

```
  conference_configured    topic/goal/roles updated
  agent_joined             agent registered
  agent_left               agent disconnected
  conference_started       round 1 begins
  round_started            new round begins (includes turn_order for round 2+)
  turn_started             next agent's turn in round-robin mode
  message_posted           agent posted a message
  agent_acted              agent completed their action for the round
  conference_ended         majority vote reached
  conference_halted        moderator halted
  conference_reset         state wiped, new session created
  moderator_message        moderator posted a message to the board
```

---

## 5. File Locking

The FileManager uses a simple lock table (dict mapping file path to lock
holder). Locks auto-expire after 180 seconds to prevent deadlock. At the MCP
layer, `acquire_file_lock` blocks on an `asyncio.Condition` when the lock is
held by another agent, retrying every 5 seconds (which also catches expiry).

```
  Agent A                        MCP / FileManager                Agent B
  ───────                        ─────────────────                ───────
     │                                  │                            │
     │  acquire_file_lock(A, file)      │                            │
     ├─────────────────────────────────►│                            │
     │                                  │  lock_table[file] = A      │
     │         {"acquired": true}       │  expires_at = now + 180s   │
     │◄─────────────────────────────────┤                            │
     │                                  │                            │
     │                                  │  acquire_file_lock(B, file)│
     │                                  │◄───────────────────────────┤
     │                                  │                            │
     │                                  │  file_manager.acquire_lock │
     │                                  │  returns False (held by A) │
     │                                  │                            │
     │                                  │  await asyncio.Condition   │
     │                                  │  .wait() — B blocks here   │
     │                                  │  (retries every 5s)        │
     │                                  │         ...                │
     │                                  │                            │
     │  release_file_lock(A, file)      │                            │
     ├─────────────────────────────────►│                            │
     │                                  │  del lock_table[file]      │
     │                                  │  condition.notify_all()    │
     │         {"released": true}       │                            │
     │◄─────────────────────────────────┤                            │
     │                                  │                            │
     │                                  │  B wakes up from Condition │
     │                                  │  file_manager.acquire_lock │
     │                                  │  returns True              │
     │                                  │  lock_table[file] = B      │
     │                                  │                            │
     │                                  │  {"acquired": true}        │
     │                                  ├───────────────────────────►│
     │                                  │                            │
```

### Auto-Expiry

```
  If 180 seconds pass without release:
    _is_lock_valid() returns False
    → next acquire_lock() call overwrites the expired entry
    → no manual cleanup needed
```

### Write Validation

```
  write_shared_file(agent_id, file_path, content)
    │
    ├─ lock exists and valid?
    │    NO  → PermissionError: "Must acquire lock before writing"
    │
    ├─ lock.agent_id == agent_id?
    │    NO  → PermissionError: "Lock held by <other>, not <you>"
    │
    └─ YES → write to disk
```

---

## 6. Session Directory Structure

Each conference session gets its own directory under `sessions/`. The
directory name is a timestamp plus the first 8 characters of the conference
state UUID. The `workspace/` subdirectory holds shared files created by
agents. A `transcript.md` is written automatically when a conference ends,
is halted, or is reset.

```
  sessions/
  ├── 20260301-143022-a1b2c3d4/
  │   ├── workspace/
  │   │   ├── design.md
  │   │   └── api_spec.json
  │   └── transcript.md
  │
  └── 20260301-151045-e5f6g7h8/
      ├── workspace/
      │   └── ...
      └── transcript.md
```

### Session ID Format

```
  YYYYMMDD-HHMMSS-xxxxxxxx
  │                │
  │                └── first 8 chars of ConferenceState.id (UUID)
  └── timestamp from first round's started_at (or now if no rounds)
```

---

## 7. Project Structure

```
  src/macf/
  ├── __init__.py              Package init
  ├── main.py                  CLI entry point (argparse) + server startup
  ├── models.py                Pydantic models (7 models, 4 enums)
  ├── conference.py            ConferenceManager (state machine, round-robin,
  │                              event emission, turn protocol)
  ├── file_manager.py          FileManager (locking, auto-expiry,
  │                              path traversal protection)
  ├── mcp_server.py            15 MCP tools + 1 MCP prompt
  ├── transcript.py            Session ID generation + transcript writing
  └── web/
      ├── __init__.py
      ├── app.py               FastAPI factory (REST + WebSocket + event wiring)
      └── static/
          └── index.html       Dashboard UI (vanilla JS, single-page)

  tests/
  ├── test_models.py           Model validation
  ├── test_conference.py       ConferenceManager unit tests
  ├── test_file_manager.py     FileManager unit tests
  ├── test_mcp_server.py       MCP tool tests
  ├── test_transcript.py       Transcript generation tests
  ├── test_web.py              Dashboard / API tests
  └── test_integration.py      End-to-end flow tests
                               (7 files, 76 tests total)

  docs/
  ├── architecture.md          This file
  ├── banner.svg               README banner image
  └── plans/                   Implementation plan documents

  examples/
  └── api_design_conference.json   Sample conference configuration
```

---

## 8. MCP Tool Inventory

All 15 tools exposed by the MCP server on port 8001 via Streamable HTTP.
"Blocks" means the tool awaits an `asyncio.Event` or `asyncio.Condition`
before returning, so the calling agent's request hangs until the condition
is met.

```
  ┌─────────────────────┬─────────┬──────────────────────────────────────────┐
  │ Tool                │ Blocks? │ Description                              │
  ├─────────────────────┼─────────┼──────────────────────────────────────────┤
  │                     │         │                                          │
  │  CONFERENCE         │         │                                          │
  │  ─────────          │         │                                          │
  │ register_agent      │  Yes    │ Join conference; blocks until configured │
  │ get_available_roles │  Yes    │ List unclaimed roles; blocks until       │
  │                     │         │   configured                             │
  │ get_conference      │  No     │ Return status, topic, round number       │
  │   _status           │         │                                          │
  │ get_board           │  No     │ Return all posted messages               │
  │ get_round_info      │  No     │ Return current round state, turn order,  │
  │                     │         │   who has acted, who is pending           │
  │ get_agents          │  No     │ List all agents and their status          │
  │                     │         │                                          │
  │  ACTIONS            │         │                                          │
  │  ───────            │         │                                          │
  │ post_message        │  No     │ Post message to board for current round  │
  │ pass_turn           │  No     │ Skip this round (nothing to add)         │
  │ vote_to_end         │  No     │ Cast vote to end the conference          │
  │                     │         │                                          │
  │  FILES              │         │                                          │
  │  ─────              │         │                                          │
  │ create_shared_file  │  Yes    │ Create file in workspace; blocks until   │
  │                     │         │   configured                             │
  │ list_shared_files   │  No     │ List all files in the workspace          │
  │ read_shared_file    │  No     │ Read file contents + lock info           │
  │ acquire_file_lock   │  Yes    │ Acquire exclusive write lock; blocks     │
  │                     │         │   until lock available (asyncio.Condition │
  │                     │         │   with 5s retry loop)                    │
  │ release_file_lock   │  No     │ Release lock; notify_all() on Condition  │
  │ write_shared_file   │  Yes    │ Write to file; blocks until configured;  │
  │                     │         │   requires holding the lock              │
  │                     │         │                                          │
  ├─────────────────────┼─────────┼──────────────────────────────────────────┤
  │                     │         │                                          │
  │  PROMPT             │         │                                          │
  │  ──────             │         │                                          │
  │ conference_briefing │  n/a    │ Returns full briefing text for an agent: │
  │                     │         │   topic, goal, role, participants,       │
  │                     │         │   protocol instructions                  │
  │                     │         │                                          │
  └─────────────────────┴─────────┴──────────────────────────────────────────┘
```

---

*Generated for MACF -- Multi-Agent Conference Framework 2*
