# Dashboard Configuration & Agent Prompt Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let the moderator configure the conference (topic, goal, roles) entirely from the browser dashboard, and display a generic copy-paste prompt that tells any agent how to connect and participate.

**Architecture:** Add a `configure` method to ConferenceManager so topic/goal/roles can be set post-creation. Add REST endpoints for configuration. Rebuild the dashboard frontend with two views: a setup view (shown when status=waiting) where the moderator configures everything and copies agent prompts, and the existing conference view (shown when status=active/completed/halted). The agent prompt is a static template with only the MCP URL interpolated — it tells the agent to connect, check roles, register, and follow the protocol.

**Tech Stack:** Same as existing — Python, FastAPI, Pydantic, vanilla HTML/CSS/JS.

---

### Task 1: ConferenceManager.configure() and generate_agent_prompt()

**Files:**
- Modify: `src/macf/conference.py`
- Modify: `tests/test_conference.py`

**Step 1: Write failing tests**

Add these tests to `tests/test_conference.py`:

```python
def test_configure_sets_topic_goal_roles():
    conf = ConferenceManager()
    conf.configure(
        topic="Build a CLI tool",
        goal="Produce a working Python CLI",
        roles=[RoleConfig(name="Architect", description="designs systems")],
    )
    assert conf.state.topic == "Build a CLI tool"
    assert conf.state.goal == "Produce a working Python CLI"
    assert len(conf._roles) == 1


def test_configure_fails_after_start():
    conf = ConferenceManager(topic="Test")
    conf.register_agent("A1")
    conf.register_agent("A2")
    conf.start()
    with pytest.raises(ValueError, match="Cannot reconfigure"):
        conf.configure(topic="New topic")
```

**Step 2: Run tests to verify they fail**

Run: `cd . && .venv/bin/pytest tests/test_conference.py::test_configure_sets_topic_goal_roles tests/test_conference.py::test_configure_fails_after_start -v`
Expected: FAIL (no `configure` method, `__init__` requires `topic`)

**Step 3: Implement changes in conference.py**

Change `__init__` to make `topic` optional (default `""`):

```python
def __init__(self, topic: str = "", goal: str = "", roles: list[RoleConfig] | None = None):
```

Add `configure` method right after `__init__`:

```python
def configure(self, topic: str, goal: str = "", roles: list[RoleConfig] | None = None) -> None:
    """Set or update conference topic, goal, and roles. Only valid before start."""
    if self.state.status != ConferenceStatus.WAITING:
        raise ValueError("Cannot reconfigure after conference has started")
    self.state.topic = topic
    self.state.goal = goal
    self._roles = roles or []
    self._emit("conference_configured", {
        "topic": topic, "goal": goal,
        "roles": [{"name": r.name, "description": r.description} for r in self._roles],
    })
```

Add `generate_agent_prompt` as a module-level function (not a method — it's static text with a URL):

```python
def generate_agent_prompt(mcp_url: str) -> str:
    """Generate the generic initial prompt to paste into any agent harness."""
    return f"""\
You are joining a multi-agent conference as a participant. A conference MCP server is available to you with tools for structured collaboration.

## Getting Started

1. Call `get_available_roles()` to see which roles are open for this conference.
2. Choose a role that fits your capabilities.
3. Call `register_agent(name="<role_name>")` to join. This returns a full briefing with the conference topic, goal, your specific instructions, the other participants, and the round protocol. Read it carefully.

## Participating

The conference runs in rounds. Each round you MUST take exactly one action:
- `post_message(agent_id, content)` — share your contribution for this round
- `pass_turn(agent_id)` — skip this round if you have nothing to add
- `vote_to_end(agent_id)` — signal that the goal has been met

Before acting each round:
- Call `get_board()` to read what others have posted.
- Call `get_round_info()` to see who has acted and who is still pending.

After acting, poll `get_conference_status()` until the next round starts or the conference ends.

## Shared Files

If the task involves producing a document or artifact:
- `list_shared_files()` and `read_shared_file(file_path)` to see existing work.
- `acquire_file_lock(agent_id, file_path)` before writing — only the lock holder can write.
- `write_shared_file(agent_id, file_path, content)` to update the file.
- `release_file_lock(agent_id, file_path)` when done so others can edit.

## Important

- You can only act ONCE per round. After posting/passing/voting, wait for the next round.
- A round completes when ALL agents have acted. Then the next round starts automatically.
- The conference ends when a majority of agents vote to end in the same round.
- Stay focused on the goal. Be concise. Build on what others have said.

MCP Server URL: {mcp_url}
"""
```

**Step 4: Run tests to verify they pass**

Run: `cd . && .venv/bin/pytest tests/test_conference.py -v`
Expected: All PASS (22 existing + 2 new = 24)

**Step 5: Commit**

```bash
git add src/macf/conference.py tests/test_conference.py
git commit -m "feat: add configure() method and generate_agent_prompt()"
```

---

### Task 2: REST API endpoints for configuration and prompt

**Files:**
- Modify: `src/macf/web/app.py`
- Modify: `tests/test_web.py`

**Step 1: Write failing tests**

Add to `tests/test_web.py`:

```python
@pytest.mark.asyncio
async def test_configure_conference(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/configure", json={
            "topic": "Design a CLI",
            "goal": "Build a working tool",
            "roles": [{"name": "Architect", "description": "designs systems", "instructions": "Focus on structure"}],
        })
        assert resp.status_code == 200
        resp = await client.get("/api/conference")
        data = resp.json()
        assert data["topic"] == "Design a CLI"
        assert data["goal"] == "Build a working tool"


@pytest.mark.asyncio
async def test_get_roles(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post("/api/configure", json={
            "topic": "Test",
            "roles": [{"name": "A1", "description": "role1"}, {"name": "A2", "description": "role2"}],
        })
        resp = await client.get("/api/roles")
        assert resp.status_code == 200
        assert len(resp.json()) == 2


@pytest.mark.asyncio
async def test_get_agent_prompt(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/prompt")
        assert resp.status_code == 200
        data = resp.json()
        assert "prompt" in data
        assert "get_available_roles" in data["prompt"]
        assert "mcp_url" in data
```

**Step 2: Run tests to verify they fail**

Run: `cd . && .venv/bin/pytest tests/test_web.py::test_configure_conference tests/test_web.py::test_get_roles tests/test_web.py::test_get_agent_prompt -v`
Expected: FAIL (endpoints don't exist)

**Step 3: Implement in web/app.py**

Add request model:

```python
class ConfigureRequest(BaseModel):
    topic: str
    goal: str = ""
    roles: list[dict] = []
```

Add to `create_app`, store the mcp_url, add endpoints:

The function signature gets a new param:
```python
def create_app(
    topic: str = "Untitled Conference",
    goal: str = "",
    roles: list | None = None,
    workspace_dir: Path | None = None,
    mcp_host: str = "127.0.0.1",
    mcp_port: int = 8001,
) -> FastAPI:
```

Add inside the function body, after the existing endpoints but before the WebSocket:

```python
    mcp_url = f"http://{mcp_host}:{mcp_port}/mcp"

    @app.post("/api/configure")
    async def configure(req: ConfigureRequest):
        from macf.models import RoleConfig
        role_configs = [RoleConfig(**r) for r in req.roles] if req.roles else None
        conference.configure(topic=req.topic, goal=req.goal, roles=role_configs)
        return {"status": "configured"}

    @app.get("/api/roles")
    async def get_roles():
        return conference.get_available_roles()

    @app.get("/api/prompt")
    async def get_prompt():
        from macf.conference import generate_agent_prompt
        return {"prompt": generate_agent_prompt(mcp_url), "mcp_url": mcp_url}
```

Also update `GET /api/conference` to include `goal` and `roles`:

```python
    @app.get("/api/conference")
    async def get_conference():
        return {
            "topic": conference.state.topic,
            "goal": conference.state.goal,
            "status": conference.state.status.value,
            "current_round": conference.state.current_round,
            "agent_count": len(conference._active_agent_ids()),
            "roles": [{"name": r.name, "description": r.description} for r in conference._roles],
        }
```

**Step 4: Run tests**

Run: `cd . && .venv/bin/pytest tests/test_web.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/macf/web/app.py tests/test_web.py
git commit -m "feat: REST endpoints for conference configuration and agent prompt"
```

---

### Task 3: Dashboard frontend — setup view with configuration and prompt display

**Files:**
- Modify: `src/macf/web/static/index.html`

This is the biggest task. The dashboard gets two views:

1. **Setup view** (shown when `status === "waiting"`): form to set topic, goal, add/remove roles, a "Start Conference" button, and a copyable agent prompt box.
2. **Conference view** (existing): agent list, message board, moderator controls.

**Step 1: Rewrite index.html**

The full HTML is large. Key changes from existing:

**New CSS classes:**
- `.setup-view` — the configuration panel, flex column centered
- `.setup-form` — form fields for topic, goal
- `.roles-list` — dynamic list of role cards with remove buttons
- `.add-role-row` — inputs + button to add a role
- `.prompt-box` — monospace pre block with the agent prompt, plus a copy button
- `.view-hidden` — `display: none` toggle class

**New HTML structure:**
```html
<div id="setupView" class="setup-view">
  <h2>Conference Setup</h2>
  <!-- Topic input -->
  <!-- Goal textarea -->
  <!-- Roles section: list + add form -->
  <!-- Agent Prompt section: readonly textarea + copy button -->
  <!-- MCP Config JSON snippet -->
  <!-- Start button (disabled until topic is set and 2+ agents connected) -->
</div>

<div id="conferenceView" class="main" style="display:none">
  <!-- existing sidebar + board -->
</div>
```

**New JS functions:**
- `saveConfig()` — POST /api/configure with form values, then refresh prompt
- `loadPrompt()` — GET /api/prompt and display in prompt box
- `addRole()` — add a role entry to the local list, call saveConfig
- `removeRole(index)` — remove role from list, call saveConfig
- `copyPrompt()` — copy prompt text to clipboard
- `startConference()` — POST /api/start, switch to conference view
- `switchView(status)` — toggle between setup and conference views based on status

**handleEvent changes:**
- On `initial_state`: call `switchView(data.status)`, populate setup form if waiting
- On `conference_started`: switch to conference view
- On `conference_configured`: update setup form if another browser tab changed it

**Step 2: Verify dashboard test still passes**

Run: `cd . && .venv/bin/pytest tests/test_web.py::test_dashboard_serves_html -v`
Expected: PASS

**Step 3: Commit**

```bash
git add src/macf/web/static/index.html
git commit -m "feat: dashboard setup view with config form and agent prompt display"
```

---

### Task 4: Update main.py to work with dashboard-driven config

**Files:**
- Modify: `src/macf/main.py`

**Step 1: Simplify main.py**

The server should start with minimal/no config since the dashboard drives it. Keep `--config` for pre-seeding but make `--topic` and `--goal` optional with empty defaults. Remove the override logic — if a config file is provided, use it to pre-configure; otherwise start blank and let the dashboard handle it.

```python
def main() -> None:
    parser = argparse.ArgumentParser(description="MACF2 - Multi-Agent Conference Framework")
    parser.add_argument("--topic", default="", help="Pre-set conference topic")
    parser.add_argument("--goal", default="", help="Pre-set conference goal")
    parser.add_argument("--config", default=None, help="JSON config file to pre-load")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind to")
    parser.add_argument("--workspace", default=None, help="Shared files directory")
    parser.add_argument("--mcp-port", type=int, default=8001, help="MCP server port")
    args = parser.parse_args()

    # Pre-load config if provided
    config = None
    if args.config:
        config = ConferenceConfig.model_validate_json(Path(args.config).read_text())

    workspace = Path(args.workspace) if args.workspace else None
    app = create_app(
        topic=args.topic or (config.topic if config else ""),
        goal=args.goal or (config.goal if config else ""),
        roles=config.roles if config else None,
        workspace_dir=workspace,
        mcp_host=args.host,
        mcp_port=args.mcp_port,
    )
    # ... rest stays the same
```

**Step 2: Verify import still works**

Run: `cd . && .venv/bin/python -c "from macf.main import main; print('OK')"`
Expected: OK

**Step 3: Commit**

```bash
git add src/macf/main.py
git commit -m "feat: simplify main.py for dashboard-driven configuration"
```

---

### Task 5: Full test pass and server verification

**Step 1: Run all tests**

Run: `cd . && .venv/bin/pytest tests/ -v --tb=short`
Expected: All PASS

**Step 2: Verify server starts**

Run the server for 3 seconds, check it prints URLs.

**Step 3: Commit any fixups**

```bash
git add -A
git commit -m "chore: final verification and cleanup"
```

---

## Summary

| Task | What | Files |
|------|------|-------|
| 1 | `configure()` method + `generate_agent_prompt()` | conference.py, test_conference.py |
| 2 | REST endpoints: /api/configure, /api/roles, /api/prompt | web/app.py, test_web.py |
| 3 | Dashboard setup view with config form + prompt display | index.html |
| 4 | Simplify main.py for dashboard-driven workflow | main.py |
| 5 | Full test pass + server verification | all |
