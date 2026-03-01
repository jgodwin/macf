# Show MCP Clients Before Registration

## Context

Currently, agents only appear in the dashboard after calling `register_agent`. The user wants to see MCP clients as soon as they connect — even before they pick a role — to help with debugging.

## Approach

FastMCP's `Context` object exposes `client_id` and `session` per-request. We inject `ctx: Context` into every MCP tool, extract the `client_id`, and track it in `ConferenceManager`. When a new `client_id` is seen for the first time, we emit a `"client_connected"` event. When `register_agent` is called, we link the `client_id` to the agent. The dashboard shows unregistered clients in the agent list with a "pending" status.

## Files to Modify

- `src/macf/models.py` — Add `PENDING` to `AgentStatus`, add `McpClient` model
- `src/macf/conference.py` — Add `track_mcp_client()`, link clients to agents on registration, include pending clients in `get_agents_info()`
- `src/macf/mcp_server.py` — Add `ctx: Context` to all tools, call `conference.track_mcp_client(ctx.client_id)` at entry
- `src/macf/web/static/index.html` — Style `pending` status badge, show pending clients in setup view
- `tests/test_conference.py` — Tests for client tracking

## Task 1: Add MCP client tracking to models and conference

### 1a. Add `PENDING` status and `McpClient` model to `models.py`

Add `PENDING = "pending"` to `AgentStatus` enum (before CONNECTED).

Add a simple model:
```python
class McpClient(BaseModel):
    client_id: str
    connected_at: datetime = Field(default_factory=_now)
    agent_id: str | None = None  # Set when register_agent links them
```

### 1b. Add client tracking to `ConferenceManager`

Add `_mcp_clients: dict[str, McpClient]` to `__init__` and `reset()`.

Add method:
```python
def track_mcp_client(self, client_id: str) -> None:
    if client_id and client_id not in self._mcp_clients:
        client = McpClient(client_id=client_id)
        self._mcp_clients[client_id] = client
        self._emit("client_connected", {"client_id": client_id})
```

### 1c. Link client to agent in `register_agent()`

Accept optional `client_id: str = ""` parameter. If provided, look up in `_mcp_clients` and set `agent_id` on the `McpClient`.

### 1d. Include pending clients in `get_agents_info()`

After the existing agents list, append entries for unlinked MCP clients:
```python
for client in self._mcp_clients.values():
    if client.agent_id is None:
        result.append({
            "id": client.client_id,
            "name": f"MCP Client ({client.client_id[:8]})",
            "role": "",
            "status": "pending",
        })
```

### 1e. Clean up on `reset()`

Clear `_mcp_clients` dict.

---

## Task 2: Add Context to MCP tools

### 2a. Add `ctx: Context` parameter to all tools in `mcp_server.py`

For every `@mcp.tool()` function, add `ctx: Context` as the first parameter and call `conference.track_mcp_client(ctx.client_id)` as the first line.

### 2b. Pass `client_id` to `register_agent()`

In the `register_agent` tool, pass `client_id=ctx.client_id` to `conference.register_agent()`.

---

## Task 3: Dashboard styling for pending clients

### 3a. Add `agent-status-pending` CSS class

Style it with a muted/pulsing appearance to distinguish from registered agents:
```css
.agent-status-pending { background: #854d0e; color: #fef08a; }
```

### 3b. Handle `client_connected` event

Add WebSocket event handler that triggers `fetchAgents()` to refresh the agent list.

---

## Task 4: Tests

- `test_track_mcp_client_new` — New client_id creates McpClient, emits event
- `test_track_mcp_client_duplicate` — Same client_id is idempotent
- `test_mcp_client_linked_on_register` — After register_agent with client_id, McpClient.agent_id is set
- `test_pending_clients_in_agents_info` — Unlinked clients appear in get_agents_info with status "pending"
- `test_linked_clients_not_in_agents_info` — Linked clients don't appear as separate pending entries
- `test_reset_clears_mcp_clients` — reset() clears _mcp_clients

---

## Verification

1. `source .venv/bin/activate && python -m pytest tests/ --tb=short` — all tests pass
2. Start server, connect an MCP client, verify it appears in dashboard before calling register_agent
3. After registration, verify the pending entry is replaced by the registered agent
