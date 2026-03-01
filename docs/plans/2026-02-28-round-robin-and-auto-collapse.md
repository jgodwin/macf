# Round-Robin Turn Taking + Auto-Collapse Rounds

## Context

Currently all agents act in parallel each round (any order). The user wants:
1. **Round-robin turn taking after round 1** — Round 1 stays parallel; round 2+ enforces one-at-a-time in registration order.
2. **Auto-collapse previous rounds** — When a new round starts, collapse all prior round groups in the dashboard.

## Files to Modify

- `src/macf2/conference.py` — Turn order tracking, enforcement, updated protocol instructions
- `src/macf2/web/static/index.html` — Auto-collapse, turn indicator in round badge, `turn_started` event handling
- `tests/test_conference.py` — New tests for round-robin enforcement

No changes needed to `models.py`, `mcp_server.py`, or `app.py` — ValueError propagates naturally through MCP tools, and new event fields are auto-broadcast.

---

## Task 1: Add round-robin turn taking to `conference.py`

### 1a. New instance state in `__init__` and `reset()`

Add `_turn_order: list[str]` and `_current_turn_index: int` to `__init__`. Clear them in `reset()`.

### 1b. Establish turn order in `start()`

Set `_turn_order` from `self.state.agents` insertion order (Python 3.7+ dict order = registration order), filtered to active agents.

### 1c. Modify `_start_new_round()`

- Always reset `_current_turn_index = 0`
- Round 1: all agents → THINKING (parallel, as today)
- Round 2+: skip disconnected agents at front, set only current-turn agent to THINKING, others to CONNECTED. Emit `round_started` with `turn_order` and `current_turn` fields.

### 1d. Add `_advance_to_next_active_turn()` helper

Skips disconnected agents in the turn order by incrementing `_current_turn_index`.

### 1e. Enforce turn order in `_record_action()`

For `current_round > 1`, check `agent_id == _turn_order[_current_turn_index]`. Raise `ValueError("Not your turn. It is {name}'s turn, not {name}'s.")` if wrong.

After recording action in round 2+, call `_advance_after_action()` instead of `_check_round_complete()`.

### 1f. Add `_advance_after_action()`

After an agent acts in round-robin mode:
- Increment turn index
- If `all_acted(active)` → round complete → check majority vote → end or new round
- Else advance to next active agent → set THINKING → emit `turn_started` event

### 1g. Handle disconnection mid-turn in `unregister_agent()`

If the disconnecting agent is the current turn holder, advance to next active agent (or complete round if all remaining have acted).

### 1h. Update `get_round_info()`

For round > 1, include `turn_order` (list of names) and `current_turn` (name or null).

### 1i. Update `PROTOCOL_INSTRUCTIONS` and `generate_agent_prompt()`

Mention round 1 is parallel, round 2+ is round-robin. Tell agents to check `get_round_info()` for whose turn it is.

---

## Task 2: Auto-collapse previous rounds + turn indicator in dashboard

### 2a. Auto-collapse on `round_started` event

Before calling `addRoundSeparator()`, add `.collapsed` class to all existing `.round-group` elements.

### 2b. Auto-collapse on initial page load

In `renderAllMessages`, after rendering, collapse all round groups except the last one.

### 2c. Handle `turn_started` event

Add handler: refresh agents (so THINKING badge updates) and update round badge to show `"Round: N — AgentName's turn"`.

### 2d. Update `round_started` handler for turn info

For round 2+, update round badge with current turn name from the event data.

---

## Task 3: Tests for round-robin enforcement

Add ~7 tests:
- Round 1 allows any order
- Round 2 enforces registration-order turn taking
- Wrong-turn agent gets ValueError
- `get_round_info()` includes `turn_order`/`current_turn` for round 2+
- `pass_turn` and `vote_to_end` respect turn order
- Disconnected agent skipped in turn order

---

## Verification

1. `source .venv/bin/activate && python -m pytest tests/ --tb=short` — all tests pass (existing 60 + ~7 new)
2. Start server, open dashboard, register 2+ agents, verify:
   - Round 1: agents can act in any order
   - Round 2+: only current-turn agent can act; others get error
   - Dashboard shows whose turn it is in round badge
   - Previous rounds auto-collapse when new round starts
   - Clicking collapsed round header re-expands it
