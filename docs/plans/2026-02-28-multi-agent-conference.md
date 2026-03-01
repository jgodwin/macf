# Multi-Agent Conference Framework (MACF2) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a round-based multi-agent collaboration framework where AI agents connect via MCP, collaborate on shared tasks through structured rounds, edit shared files with locking, and are observed/controlled through a real-time browser dashboard.

**Architecture:** A central conference server acts as both an MCP server (agents connect as MCP clients and interact through tools) and a FastAPI web server (browser dashboard via WebSockets). The conference operates in rounds: each round, every agent independently posts a message, passes, or votes to end. When all agents have acted, the round completes. A majority vote-to-end concludes the conference. Shared files use exclusive write locks with configurable expiry.

**Tech Stack:** Python 3.11+, FastMCP (MCP server), FastAPI + uvicorn (web server + WebSocket), Pydantic (data models), pytest + pytest-asyncio (testing)

---

### Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `src/macf/__init__.py`
- Create: `src/macf/models.py` (empty placeholder)
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

**Step 1: Create pyproject.toml**

```toml
[project]
name = "macf2"
version = "0.1.0"
description = "Multi-Agent Conference Framework"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.32.0",
    "mcp[cli]>=1.0.0",
    "pydantic>=2.0.0",
    "websockets>=13.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.24.0",
    "httpx>=0.27.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/macf"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

**Step 2: Create directory structure and placeholder files**

```bash
mkdir -p src/macf/web/static tests
touch src/macf/__init__.py tests/__init__.py
```

**Step 3: Create tests/conftest.py**

```python
import pytest
```

**Step 4: Install dependencies**

Run: `cd . && pip install -e ".[dev]"`

**Step 5: Verify pytest runs**

Run: `cd . && pytest --co -q`
Expected: "no tests ran" (no errors)

**Step 6: Initialize git repo and commit**

```bash
cd .
git init
git add pyproject.toml src/ tests/
git commit -m "chore: project scaffolding"
```

---

### Task 2: Core Data Models

**Files:**
- Create: `src/macf/models.py`
- Create: `tests/test_models.py`

**Step 1: Write tests for data models**

```python
# tests/test_models.py
import pytest
from datetime import datetime, timezone
from macf.models import (
    AgentInfo, Message, RoundAction, Round, ConferenceState,
    AgentStatus, RoundStatus, ConferenceStatus, ActionType,
)


def test_agent_info_creation():
    agent = AgentInfo(name="Architect", role="system designer")
    assert agent.name == "Architect"
    assert agent.role == "system designer"
    assert agent.status == AgentStatus.CONNECTED
    assert agent.id  # auto-generated


def test_message_creation():
    msg = Message(
        agent_id="a1",
        agent_name="Architect",
        round_number=1,
        content="We should use a modular design.",
    )
    assert msg.content == "We should use a modular design."
    assert msg.id  # auto-generated
    assert msg.timestamp  # auto-set


def test_round_action_creation():
    action = RoundAction(agent_id="a1", type=ActionType.MESSAGE, content="hello")
    assert action.type == ActionType.MESSAGE
    assert action.content == "hello"


def test_round_creation():
    r = Round(number=1)
    assert r.status == RoundStatus.ACTIVE
    assert r.actions == {}


def test_round_all_agents_acted():
    r = Round(number=1)
    r.actions["a1"] = RoundAction(agent_id="a1", type=ActionType.MESSAGE, content="hi")
    r.actions["a2"] = RoundAction(agent_id="a2", type=ActionType.PASS)
    assert r.all_acted({"a1", "a2"}) is True
    assert r.all_acted({"a1", "a2", "a3"}) is False


def test_round_vote_count():
    r = Round(number=1)
    r.actions["a1"] = RoundAction(agent_id="a1", type=ActionType.VOTE_TO_END)
    r.actions["a2"] = RoundAction(agent_id="a2", type=ActionType.MESSAGE, content="more work")
    r.actions["a3"] = RoundAction(agent_id="a3", type=ActionType.VOTE_TO_END)
    assert r.end_vote_count() == 2


def test_conference_state_creation():
    cs = ConferenceState(topic="Design a REST API")
    assert cs.topic == "Design a REST API"
    assert cs.status == ConferenceStatus.WAITING
    assert cs.agents == {}
    assert cs.rounds == []
    assert cs.messages == []
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_models.py -v`
Expected: FAIL (import errors)

**Step 3: Implement data models**

```python
# src/macf/models.py
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from pydantic import BaseModel, Field


class AgentStatus(str, Enum):
    CONNECTED = "connected"
    THINKING = "thinking"
    ACTED = "acted"
    DISCONNECTED = "disconnected"


class RoundStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"


class ConferenceStatus(str, Enum):
    WAITING = "waiting"
    ACTIVE = "active"
    COMPLETED = "completed"
    HALTED = "halted"


class ActionType(str, Enum):
    MESSAGE = "message"
    PASS = "pass"
    VOTE_TO_END = "vote_to_end"


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AgentInfo(BaseModel):
    id: str = Field(default_factory=_uuid)
    name: str
    role: str = ""
    instructions: str = ""
    status: AgentStatus = AgentStatus.CONNECTED
    connected_at: datetime = Field(default_factory=_now)


class Message(BaseModel):
    id: str = Field(default_factory=_uuid)
    agent_id: str
    agent_name: str
    round_number: int
    content: str
    timestamp: datetime = Field(default_factory=_now)


class RoundAction(BaseModel):
    agent_id: str
    type: ActionType
    content: str | None = None
    timestamp: datetime = Field(default_factory=_now)


class Round(BaseModel):
    number: int
    status: RoundStatus = RoundStatus.ACTIVE
    actions: dict[str, RoundAction] = Field(default_factory=dict)
    started_at: datetime = Field(default_factory=_now)
    ended_at: datetime | None = None

    def all_acted(self, agent_ids: set[str]) -> bool:
        return agent_ids == set(self.actions.keys())

    def end_vote_count(self) -> int:
        return sum(1 for a in self.actions.values() if a.type == ActionType.VOTE_TO_END)


class ConferenceState(BaseModel):
    id: str = Field(default_factory=_uuid)
    topic: str
    status: ConferenceStatus = ConferenceStatus.WAITING
    agents: dict[str, AgentInfo] = Field(default_factory=dict)
    rounds: list[Round] = Field(default_factory=list)
    messages: list[Message] = Field(default_factory=list)
    moderator_messages: list[Message] = Field(default_factory=list)
    current_round: int = 0
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_models.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/macf/models.py tests/test_models.py
git commit -m "feat: core data models for conference, agents, rounds, messages"
```

---

### Task 3: Conference Manager

**Files:**
- Create: `src/macf/conference.py`
- Create: `tests/test_conference.py`

**Step 1: Write tests for conference manager**

```python
# tests/test_conference.py
import pytest
from macf.conference import ConferenceManager
from macf.models import ConferenceStatus, ActionType, AgentStatus


@pytest.fixture
def conf():
    return ConferenceManager(topic="Design a REST API")


def test_register_agent(conf):
    agent_id = conf.register_agent("Architect", role="system designer")
    assert agent_id in conf.state.agents
    assert conf.state.agents[agent_id].name == "Architect"


def test_register_agent_duplicate_name(conf):
    conf.register_agent("Architect")
    with pytest.raises(ValueError, match="already registered"):
        conf.register_agent("Architect")


def test_unregister_agent(conf):
    agent_id = conf.register_agent("Architect")
    conf.unregister_agent(agent_id)
    assert conf.state.agents[agent_id].status == AgentStatus.DISCONNECTED


def test_start_conference(conf):
    conf.register_agent("A1")
    conf.register_agent("A2")
    conf.start()
    assert conf.state.status == ConferenceStatus.ACTIVE
    assert conf.state.current_round == 1
    assert len(conf.state.rounds) == 1


def test_start_conference_requires_agents(conf):
    with pytest.raises(ValueError, match="at least 2"):
        conf.start()


def test_post_message(conf):
    a1 = conf.register_agent("A1")
    a2 = conf.register_agent("A2")
    conf.start()
    result = conf.post_message(a1, "I think we should use REST.")
    assert result is True
    assert len(conf.state.messages) == 1
    assert conf.state.messages[0].content == "I think we should use REST."


def test_post_message_twice_same_round(conf):
    a1 = conf.register_agent("A1")
    conf.register_agent("A2")
    conf.start()
    conf.post_message(a1, "first")
    with pytest.raises(ValueError, match="already acted"):
        conf.post_message(a1, "second")


def test_pass_turn(conf):
    a1 = conf.register_agent("A1")
    conf.register_agent("A2")
    conf.start()
    conf.pass_turn(a1)
    current_round = conf.state.rounds[0]
    assert current_round.actions[a1].type == ActionType.PASS


def test_vote_to_end(conf):
    a1 = conf.register_agent("A1")
    conf.register_agent("A2")
    conf.start()
    conf.vote_to_end(a1)
    current_round = conf.state.rounds[0]
    assert current_round.actions[a1].type == ActionType.VOTE_TO_END


def test_round_advances_when_all_acted(conf):
    a1 = conf.register_agent("A1")
    a2 = conf.register_agent("A2")
    conf.start()
    conf.post_message(a1, "hello")
    conf.pass_turn(a2)
    assert conf.state.current_round == 2
    assert len(conf.state.rounds) == 2


def test_conference_ends_on_majority_vote(conf):
    a1 = conf.register_agent("A1")
    a2 = conf.register_agent("A2")
    a3 = conf.register_agent("A3")
    conf.start()
    conf.vote_to_end(a1)
    conf.vote_to_end(a2)
    conf.post_message(a3, "but wait...")
    assert conf.state.status == ConferenceStatus.COMPLETED


def test_halt_conference(conf):
    a1 = conf.register_agent("A1")
    conf.register_agent("A2")
    conf.start()
    conf.halt("Going off the rails")
    assert conf.state.status == ConferenceStatus.HALTED


def test_moderator_message(conf):
    a1 = conf.register_agent("A1")
    conf.register_agent("A2")
    conf.start()
    conf.add_moderator_message("Please focus on the API design.")
    assert len(conf.state.moderator_messages) == 1
    assert conf.state.moderator_messages[0].content == "Please focus on the API design."


def test_get_board(conf):
    a1 = conf.register_agent("A1")
    a2 = conf.register_agent("A2")
    conf.start()
    conf.post_message(a1, "hello")
    conf.post_message(a2, "world")
    board = conf.get_board()
    assert len(board) == 2


def test_get_round_info(conf):
    a1 = conf.register_agent("A1")
    conf.register_agent("A2")
    conf.start()
    info = conf.get_round_info()
    assert info["round_number"] == 1
    assert info["status"] == "active"
    assert "A1" in info["pending"]
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_conference.py -v`
Expected: FAIL (import errors)

**Step 3: Implement ConferenceManager**

```python
# src/macf/conference.py
from __future__ import annotations

import asyncio
from typing import Any, Callable, Coroutine

from macf.models import (
    ActionType,
    AgentInfo,
    AgentStatus,
    ConferenceState,
    ConferenceStatus,
    Message,
    Round,
    RoundAction,
    RoundStatus,
)


class ConferenceManager:
    def __init__(self, topic: str):
        self.state = ConferenceState(topic=topic)
        self._event_listeners: list[Callable[[str, dict], Coroutine]] = []

    def on_event(self, callback: Callable[[str, dict], Coroutine]) -> None:
        self._event_listeners.append(callback)

    def _emit(self, event_type: str, data: dict) -> None:
        for listener in self._event_listeners:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(listener(event_type, data))
            except RuntimeError:
                pass  # No running loop (sync context / tests)

    def _active_agent_ids(self) -> set[str]:
        return {
            aid for aid, a in self.state.agents.items()
            if a.status != AgentStatus.DISCONNECTED
        }

    def register_agent(self, name: str, role: str = "", instructions: str = "") -> str:
        for a in self.state.agents.values():
            if a.name == name and a.status != AgentStatus.DISCONNECTED:
                raise ValueError(f"Agent '{name}' already registered")
        agent = AgentInfo(name=name, role=role, instructions=instructions)
        self.state.agents[agent.id] = agent
        self._emit("agent_joined", {"agent_id": agent.id, "name": name, "role": role})
        return agent.id

    def unregister_agent(self, agent_id: str) -> None:
        if agent_id not in self.state.agents:
            raise ValueError(f"Unknown agent: {agent_id}")
        self.state.agents[agent_id].status = AgentStatus.DISCONNECTED
        self._emit("agent_left", {"agent_id": agent_id})

    def start(self) -> None:
        active = self._active_agent_ids()
        if len(active) < 2:
            raise ValueError("Need at least 2 agents to start")
        self.state.status = ConferenceStatus.ACTIVE
        self._start_new_round()
        self._emit("conference_started", {"topic": self.state.topic})

    def _start_new_round(self) -> None:
        self.state.current_round += 1
        new_round = Round(number=self.state.current_round)
        self.state.rounds.append(new_round)
        for aid in self._active_agent_ids():
            self.state.agents[aid].status = AgentStatus.THINKING
        self._emit("round_started", {"round_number": self.state.current_round})

    def _current_round(self) -> Round:
        if not self.state.rounds:
            raise ValueError("Conference has not started")
        return self.state.rounds[-1]

    def _check_active(self) -> None:
        if self.state.status != ConferenceStatus.ACTIVE:
            raise ValueError(f"Conference is {self.state.status.value}, not active")

    def _check_agent(self, agent_id: str) -> None:
        if agent_id not in self.state.agents:
            raise ValueError(f"Unknown agent: {agent_id}")
        if self.state.agents[agent_id].status == AgentStatus.DISCONNECTED:
            raise ValueError("Agent is disconnected")

    def _record_action(self, agent_id: str, action: RoundAction) -> None:
        self._check_active()
        self._check_agent(agent_id)
        current = self._current_round()
        if agent_id in current.actions:
            raise ValueError("Agent already acted this round")
        current.actions[agent_id] = action
        self.state.agents[agent_id].status = AgentStatus.ACTED
        self._emit("agent_acted", {
            "agent_id": agent_id,
            "action_type": action.type.value,
            "round_number": current.number,
        })
        self._check_round_complete()

    def post_message(self, agent_id: str, content: str) -> bool:
        agent = self.state.agents[agent_id]
        msg = Message(
            agent_id=agent_id,
            agent_name=agent.name,
            round_number=self.state.current_round,
            content=content,
        )
        self.state.messages.append(msg)
        self._record_action(
            agent_id,
            RoundAction(agent_id=agent_id, type=ActionType.MESSAGE, content=content),
        )
        self._emit("message_posted", {
            "agent_id": agent_id,
            "agent_name": agent.name,
            "content": content,
            "round_number": self.state.current_round,
        })
        return True

    def pass_turn(self, agent_id: str) -> None:
        self._record_action(
            agent_id,
            RoundAction(agent_id=agent_id, type=ActionType.PASS),
        )

    def vote_to_end(self, agent_id: str) -> None:
        self._record_action(
            agent_id,
            RoundAction(agent_id=agent_id, type=ActionType.VOTE_TO_END),
        )

    def _check_round_complete(self) -> None:
        current = self._current_round()
        active = self._active_agent_ids()
        if not current.all_acted(active):
            return
        current.status = RoundStatus.COMPLETED
        from macf.models import _now
        current.ended_at = _now()
        votes = current.end_vote_count()
        if votes > len(active) / 2:
            self.state.status = ConferenceStatus.COMPLETED
            self._emit("conference_ended", {"reason": "majority_vote"})
        else:
            self._start_new_round()

    def halt(self, reason: str = "") -> None:
        self.state.status = ConferenceStatus.HALTED
        self._emit("conference_halted", {"reason": reason})

    def add_moderator_message(self, content: str) -> None:
        msg = Message(
            agent_id="moderator",
            agent_name="Moderator",
            round_number=self.state.current_round,
            content=content,
        )
        self.state.moderator_messages.append(msg)
        self.state.messages.append(msg)
        self._emit("moderator_message", {"content": content})

    def get_board(self) -> list[dict]:
        return [m.model_dump() for m in self.state.messages]

    def get_round_info(self) -> dict:
        current = self._current_round()
        active = self._active_agent_ids()
        acted = set(current.actions.keys())
        pending_ids = active - acted
        pending_names = [
            self.state.agents[aid].name for aid in pending_ids
        ]
        return {
            "round_number": current.number,
            "status": current.status.value,
            "acted": [
                {
                    "agent": self.state.agents[aid].name,
                    "action": act.type.value,
                }
                for aid, act in current.actions.items()
            ],
            "pending": pending_names,
        }

    def get_agents_info(self) -> list[dict]:
        return [
            {
                "id": a.id,
                "name": a.name,
                "role": a.role,
                "status": a.status.value,
            }
            for a in self.state.agents.values()
        ]
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_conference.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/macf/conference.py tests/test_conference.py
git commit -m "feat: conference manager with round-based collaboration"
```

---

### Task 4: File Manager with Locking

**Files:**
- Create: `src/macf/file_manager.py`
- Create: `tests/test_file_manager.py`

**Step 1: Write tests for file manager**

```python
# tests/test_file_manager.py
import pytest
import tempfile
from pathlib import Path
from macf.file_manager import FileManager


@pytest.fixture
def fm(tmp_path):
    return FileManager(workspace_dir=tmp_path)


def test_create_file(fm):
    fm.create_file("design.md", "# Design Doc\n")
    assert fm.read_file("design.md") == "# Design Doc\n"


def test_list_files(fm):
    fm.create_file("a.md", "a")
    fm.create_file("b.md", "b")
    files = fm.list_files()
    assert set(files) == {"a.md", "b.md"}


def test_read_nonexistent_file(fm):
    with pytest.raises(FileNotFoundError):
        fm.read_file("nope.md")


def test_acquire_lock(fm):
    fm.create_file("doc.md", "hello")
    assert fm.acquire_lock("doc.md", "agent1") is True
    lock = fm.get_lock_info("doc.md")
    assert lock["agent_id"] == "agent1"


def test_acquire_lock_conflict(fm):
    fm.create_file("doc.md", "hello")
    fm.acquire_lock("doc.md", "agent1")
    assert fm.acquire_lock("doc.md", "agent2") is False


def test_release_lock(fm):
    fm.create_file("doc.md", "hello")
    fm.acquire_lock("doc.md", "agent1")
    fm.release_lock("doc.md", "agent1")
    assert fm.get_lock_info("doc.md") is None


def test_release_lock_wrong_agent(fm):
    fm.create_file("doc.md", "hello")
    fm.acquire_lock("doc.md", "agent1")
    with pytest.raises(ValueError, match="not held by"):
        fm.release_lock("doc.md", "agent2")


def test_write_locked_file(fm):
    fm.create_file("doc.md", "old")
    fm.acquire_lock("doc.md", "agent1")
    fm.write_file("doc.md", "new", "agent1")
    assert fm.read_file("doc.md") == "new"


def test_write_without_lock(fm):
    fm.create_file("doc.md", "old")
    with pytest.raises(PermissionError, match="lock"):
        fm.write_file("doc.md", "new", "agent1")


def test_write_wrong_lock_holder(fm):
    fm.create_file("doc.md", "old")
    fm.acquire_lock("doc.md", "agent1")
    with pytest.raises(PermissionError, match="held by agent1"):
        fm.write_file("doc.md", "new", "agent2")


def test_lock_expiry(fm):
    fm.create_file("doc.md", "hello")
    fm.acquire_lock("doc.md", "agent1", timeout_seconds=0)
    # Lock should be expired immediately
    assert fm.acquire_lock("doc.md", "agent2") is True


def test_release_all_for_agent(fm):
    fm.create_file("a.md", "a")
    fm.create_file("b.md", "b")
    fm.acquire_lock("a.md", "agent1")
    fm.acquire_lock("b.md", "agent1")
    fm.release_all_locks("agent1")
    assert fm.get_lock_info("a.md") is None
    assert fm.get_lock_info("b.md") is None
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_file_manager.py -v`
Expected: FAIL (import errors)

**Step 3: Implement FileManager**

```python
# src/macf/file_manager.py
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path


@dataclass
class FileLock:
    file_path: str
    agent_id: str
    acquired_at: datetime
    expires_at: datetime


class FileManager:
    DEFAULT_LOCK_TIMEOUT = 300  # seconds

    def __init__(self, workspace_dir: Path):
        self.workspace_dir = Path(workspace_dir)
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, FileLock] = {}

    def _resolve(self, file_path: str) -> Path:
        resolved = (self.workspace_dir / file_path).resolve()
        if not str(resolved).startswith(str(self.workspace_dir.resolve())):
            raise ValueError("Path traversal not allowed")
        return resolved

    def create_file(self, file_path: str, content: str = "") -> None:
        full = self._resolve(file_path)
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content)

    def read_file(self, file_path: str) -> str:
        full = self._resolve(file_path)
        if not full.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        return full.read_text()

    def list_files(self) -> list[str]:
        return [
            str(p.relative_to(self.workspace_dir))
            for p in self.workspace_dir.rglob("*")
            if p.is_file()
        ]

    def _is_lock_valid(self, lock: FileLock) -> bool:
        return datetime.now(timezone.utc) < lock.expires_at

    def acquire_lock(
        self, file_path: str, agent_id: str, timeout_seconds: int | None = None
    ) -> bool:
        if timeout_seconds is None:
            timeout_seconds = self.DEFAULT_LOCK_TIMEOUT
        full = self._resolve(file_path)
        if not full.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        existing = self._locks.get(file_path)
        if existing and self._is_lock_valid(existing):
            if existing.agent_id == agent_id:
                return True  # already holds it
            return False
        now = datetime.now(timezone.utc)
        self._locks[file_path] = FileLock(
            file_path=file_path,
            agent_id=agent_id,
            acquired_at=now,
            expires_at=now + timedelta(seconds=timeout_seconds),
        )
        return True

    def release_lock(self, file_path: str, agent_id: str) -> None:
        lock = self._locks.get(file_path)
        if not lock or not self._is_lock_valid(lock):
            return  # no lock to release
        if lock.agent_id != agent_id:
            raise ValueError(f"Lock on {file_path} not held by {agent_id}")
        del self._locks[file_path]

    def release_all_locks(self, agent_id: str) -> None:
        to_remove = [
            fp for fp, lock in self._locks.items()
            if lock.agent_id == agent_id
        ]
        for fp in to_remove:
            del self._locks[fp]

    def get_lock_info(self, file_path: str) -> dict | None:
        lock = self._locks.get(file_path)
        if not lock or not self._is_lock_valid(lock):
            return None
        return {
            "file_path": lock.file_path,
            "agent_id": lock.agent_id,
            "acquired_at": lock.acquired_at.isoformat(),
            "expires_at": lock.expires_at.isoformat(),
        }

    def write_file(self, file_path: str, content: str, agent_id: str) -> None:
        full = self._resolve(file_path)
        lock = self._locks.get(file_path)
        if not lock or not self._is_lock_valid(lock):
            raise PermissionError(f"Must acquire lock on {file_path} before writing")
        if lock.agent_id != agent_id:
            raise PermissionError(
                f"Lock on {file_path} held by {lock.agent_id}, not {agent_id}"
            )
        full.write_text(content)
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_file_manager.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/macf/file_manager.py tests/test_file_manager.py
git commit -m "feat: file manager with exclusive write locking"
```

---

### Task 5: MCP Server

**Files:**
- Create: `src/macf/mcp_server.py`
- Create: `tests/test_mcp_server.py`

This task creates the MCP server that exposes conference operations as tools. Agents connect to this server and use the tools to participate.

**Step 1: Write tests for MCP tools**

```python
# tests/test_mcp_server.py
import pytest
import json
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from macf.mcp_server import create_mcp_server


@pytest.fixture
def mcp_app():
    """Create a fresh MCP server with conference for each test."""
    return create_mcp_server(topic="Test conference")


@pytest.mark.asyncio
async def test_list_tools(mcp_app):
    mcp = mcp_app["mcp"]
    tools = await mcp._tool_manager.list_tools()
    tool_names = {t.name for t in tools}
    assert "register_agent" in tool_names
    assert "post_message" in tool_names
    assert "pass_turn" in tool_names
    assert "vote_to_end" in tool_names
    assert "get_board" in tool_names
    assert "get_round_info" in tool_names
    assert "get_agents" in tool_names
    assert "acquire_file_lock" in tool_names
    assert "release_file_lock" in tool_names
    assert "read_shared_file" in tool_names
    assert "write_shared_file" in tool_names
    assert "list_shared_files" in tool_names
    assert "create_shared_file" in tool_names


@pytest.mark.asyncio
async def test_register_and_get_agents(mcp_app):
    conference = mcp_app["conference"]
    # Direct conference manager test since MCP tool calls need a client session
    agent_id = conference.register_agent("TestAgent", role="tester")
    agents = conference.get_agents_info()
    assert len(agents) == 1
    assert agents[0]["name"] == "TestAgent"


@pytest.mark.asyncio
async def test_full_round_flow(mcp_app):
    conference = mcp_app["conference"]
    a1 = conference.register_agent("Agent1")
    a2 = conference.register_agent("Agent2")
    conference.start()
    conference.post_message(a1, "Let's collaborate")
    conference.pass_turn(a2)
    # Should have advanced to round 2
    assert conference.state.current_round == 2
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_mcp_server.py -v`
Expected: FAIL (import errors)

**Step 3: Implement MCP server**

```python
# src/macf/mcp_server.py
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from mcp.server.fastmcp import FastMCP, Context

from macf.conference import ConferenceManager
from macf.file_manager import FileManager


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
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_mcp_server.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/macf/mcp_server.py tests/test_mcp_server.py
git commit -m "feat: MCP server exposing conference tools"
```

---

### Task 6: Web Dashboard Backend (FastAPI + WebSocket)

**Files:**
- Create: `src/macf/web/app.py`
- Create: `src/macf/web/__init__.py`
- Create: `tests/test_web.py`

**Step 1: Write tests for web endpoints**

```python
# tests/test_web.py
import pytest
import json
from httpx import AsyncClient, ASGITransport
from macf.web.app import create_app


@pytest.fixture
def app():
    return create_app(topic="Test Conference")


@pytest.mark.asyncio
async def test_health_endpoint(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_conference_status(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/conference")
        assert resp.status_code == 200
        data = resp.json()
        assert data["topic"] == "Test Conference"


@pytest.mark.asyncio
async def test_agents_endpoint(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/agents")
        assert resp.status_code == 200
        assert resp.json() == []


@pytest.mark.asyncio
async def test_moderator_message(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Need to register agents and start conference first
        resp = await client.post("/api/register", json={"name": "A1"})
        assert resp.status_code == 200
        resp = await client.post("/api/register", json={"name": "A2"})
        assert resp.status_code == 200
        resp = await client.post("/api/start")
        assert resp.status_code == 200
        resp = await client.post(
            "/api/moderator/message",
            json={"content": "Focus please"},
        )
        assert resp.status_code == 200


@pytest.mark.asyncio
async def test_halt_endpoint(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/register", json={"name": "A1"})
        resp = await client.post("/api/register", json={"name": "A2"})
        resp = await client.post("/api/start")
        resp = await client.post("/api/halt", json={"reason": "Off topic"})
        assert resp.status_code == 200
        resp = await client.get("/api/conference")
        assert resp.json()["status"] == "halted"


@pytest.mark.asyncio
async def test_dashboard_serves_html(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_web.py -v`
Expected: FAIL (import errors)

**Step 3: Create web/__init__.py**

```python
# src/macf/web/__init__.py
```

**Step 4: Implement web app**

```python
# src/macf/web/app.py
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from macf.conference import ConferenceManager
from macf.file_manager import FileManager
from macf.mcp_server import create_mcp_server


class RegisterRequest(BaseModel):
    name: str
    role: str = ""


class ModeratorMessageRequest(BaseModel):
    content: str


class HaltRequest(BaseModel):
    reason: str = ""


class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict) -> None:
        data = json.dumps(message, default=str)
        disconnected = []
        for conn in self.active_connections:
            try:
                await conn.send_text(data)
            except Exception:
                disconnected.append(conn)
        for conn in disconnected:
            self.disconnect(conn)


def create_app(
    topic: str = "Untitled Conference",
    workspace_dir: Path | None = None,
) -> FastAPI:
    app = FastAPI(title="MACF2 Dashboard")
    ws_manager = ConnectionManager()

    mcp_components = create_mcp_server(topic=topic, workspace_dir=workspace_dir)
    conference: ConferenceManager = mcp_components["conference"]
    file_manager: FileManager = mcp_components["file_manager"]
    mcp = mcp_components["mcp"]

    # Wire conference events to WebSocket broadcast
    async def on_conference_event(event_type: str, data: dict) -> None:
        await ws_manager.broadcast({"event": event_type, **data})

    conference.on_event(on_conference_event)

    # --- REST endpoints for dashboard ---

    @app.get("/api/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/conference")
    async def get_conference():
        return {
            "topic": conference.state.topic,
            "status": conference.state.status.value,
            "current_round": conference.state.current_round,
            "agent_count": len(conference._active_agent_ids()),
        }

    @app.get("/api/agents")
    async def get_agents():
        return conference.get_agents_info()

    @app.get("/api/board")
    async def get_board():
        return conference.get_board()

    @app.get("/api/round")
    async def get_round():
        if not conference.state.rounds:
            return {"round_number": 0, "status": "waiting"}
        return conference.get_round_info()

    @app.get("/api/files")
    async def get_files():
        return file_manager.list_files()

    @app.post("/api/register")
    async def register(req: RegisterRequest):
        agent_id = conference.register_agent(req.name, role=req.role)
        return {"agent_id": agent_id}

    @app.post("/api/start")
    async def start():
        conference.start()
        return {"status": "started"}

    @app.post("/api/moderator/message")
    async def moderator_message(req: ModeratorMessageRequest):
        conference.add_moderator_message(req.content)
        return {"status": "sent"}

    @app.post("/api/halt")
    async def halt(req: HaltRequest):
        conference.halt(req.reason)
        return {"status": "halted"}

    # --- WebSocket for real-time updates ---

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        await ws_manager.connect(websocket)
        try:
            # Send current state on connect
            await websocket.send_text(json.dumps({
                "event": "initial_state",
                "topic": conference.state.topic,
                "status": conference.state.status.value,
                "agents": conference.get_agents_info(),
                "messages": conference.get_board(),
                "current_round": conference.state.current_round,
            }, default=str))
            while True:
                data = await websocket.receive_text()
                msg = json.loads(data)
                if msg.get("type") == "moderator_message":
                    conference.add_moderator_message(msg["content"])
                elif msg.get("type") == "halt":
                    conference.halt(msg.get("reason", ""))
        except WebSocketDisconnect:
            ws_manager.disconnect(websocket)

    # --- Dashboard HTML ---

    @app.get("/", response_class=HTMLResponse)
    async def dashboard():
        html_path = Path(__file__).parent / "static" / "index.html"
        return HTMLResponse(html_path.read_text())

    # --- Mount MCP ---
    # Store mcp on app for external access
    app.state.mcp = mcp
    app.state.conference = conference
    app.state.file_manager = file_manager

    return app
```

**Step 5: Run tests to verify they pass**

Run: `pytest tests/test_web.py -v`
Expected: All PASS (except dashboard HTML - handled in next task)

**Step 6: Commit**

```bash
git add src/macf/web/ tests/test_web.py
git commit -m "feat: FastAPI web dashboard with REST and WebSocket endpoints"
```

---

### Task 7: Web Dashboard Frontend

**Files:**
- Create: `src/macf/web/static/index.html`

**Step 1: Create the dashboard HTML/CSS/JS**

This is a single-page application that connects via WebSocket and displays the conference in real time. It includes:
- Agent list with status indicators
- Message board with round separators
- Moderator input for sending messages
- Halt button
- Auto-reconnecting WebSocket

```html
<!-- src/macf/web/static/index.html -->
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>MACF2 - Conference Dashboard</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: #0f172a; color: #e2e8f0;
      display: flex; flex-direction: column; height: 100vh;
    }
    header {
      background: #1e293b; padding: 16px 24px;
      border-bottom: 1px solid #334155;
      display: flex; justify-content: space-between; align-items: center;
    }
    header h1 { font-size: 20px; color: #f1f5f9; }
    .status-badge {
      padding: 4px 12px; border-radius: 12px; font-size: 13px; font-weight: 600;
    }
    .status-waiting { background: #854d0e; color: #fef3c7; }
    .status-active { background: #166534; color: #bbf7d0; }
    .status-completed { background: #1e40af; color: #bfdbfe; }
    .status-halted { background: #991b1b; color: #fecaca; }

    .main { display: flex; flex: 1; overflow: hidden; }

    .sidebar {
      width: 280px; background: #1e293b; padding: 16px;
      border-right: 1px solid #334155; overflow-y: auto;
    }
    .sidebar h2 { font-size: 14px; text-transform: uppercase; color: #94a3b8; margin-bottom: 12px; }
    .agent-card {
      background: #334155; border-radius: 8px; padding: 12px; margin-bottom: 8px;
    }
    .agent-card .name { font-weight: 600; color: #f1f5f9; }
    .agent-card .role { font-size: 12px; color: #94a3b8; margin-top: 2px; }
    .agent-card .agent-status {
      display: inline-block; margin-top: 6px; padding: 2px 8px;
      border-radius: 8px; font-size: 11px; font-weight: 600;
    }
    .agent-status-connected { background: #166534; color: #bbf7d0; }
    .agent-status-thinking { background: #854d0e; color: #fef3c7; }
    .agent-status-acted { background: #1e40af; color: #bfdbfe; }
    .agent-status-disconnected { background: #991b1b; color: #fecaca; }

    .board {
      flex: 1; display: flex; flex-direction: column; overflow: hidden;
    }
    .round-header {
      background: #1e293b; padding: 8px 24px; font-size: 13px;
      color: #94a3b8; border-bottom: 1px solid #334155; text-align: center;
      font-weight: 600;
    }
    .messages {
      flex: 1; overflow-y: auto; padding: 16px 24px;
    }
    .message {
      background: #1e293b; border-radius: 8px; padding: 12px 16px;
      margin-bottom: 12px; border-left: 3px solid #3b82f6;
    }
    .message.moderator { border-left-color: #f59e0b; background: #1c1917; }
    .message .msg-header {
      display: flex; justify-content: space-between; margin-bottom: 6px;
    }
    .message .msg-author { font-weight: 600; color: #60a5fa; font-size: 14px; }
    .message.moderator .msg-author { color: #fbbf24; }
    .message .msg-time { font-size: 12px; color: #64748b; }
    .message .msg-body { font-size: 14px; line-height: 1.6; white-space: pre-wrap; }
    .pass-notice, .vote-notice {
      text-align: center; color: #64748b; font-size: 13px;
      margin-bottom: 12px; font-style: italic;
    }
    .vote-notice { color: #f59e0b; }

    .controls {
      background: #1e293b; padding: 16px 24px;
      border-top: 1px solid #334155;
      display: flex; gap: 12px; align-items: center;
    }
    .controls input {
      flex: 1; background: #0f172a; border: 1px solid #334155;
      border-radius: 8px; padding: 10px 16px; color: #e2e8f0;
      font-size: 14px; outline: none;
    }
    .controls input:focus { border-color: #3b82f6; }
    .controls button {
      padding: 10px 20px; border: none; border-radius: 8px;
      font-size: 14px; font-weight: 600; cursor: pointer;
    }
    .btn-send { background: #3b82f6; color: white; }
    .btn-send:hover { background: #2563eb; }
    .btn-halt { background: #dc2626; color: white; }
    .btn-halt:hover { background: #b91c1c; }

    .connection-status {
      font-size: 12px; display: flex; align-items: center; gap: 6px;
    }
    .dot {
      width: 8px; height: 8px; border-radius: 50%; display: inline-block;
    }
    .dot-connected { background: #22c55e; }
    .dot-disconnected { background: #ef4444; }
  </style>
</head>
<body>
  <header>
    <div>
      <h1 id="topic">MACF2 Conference</h1>
      <div class="connection-status" id="connStatus">
        <span class="dot dot-disconnected" id="connDot"></span>
        <span id="connText">Disconnected</span>
      </div>
    </div>
    <div>
      <span id="roundBadge" style="margin-right:12px; font-size:14px; color:#94a3b8;">Round: -</span>
      <span class="status-badge status-waiting" id="statusBadge">waiting</span>
    </div>
  </header>

  <div class="main">
    <div class="sidebar">
      <h2>Agents</h2>
      <div id="agentList"></div>
    </div>
    <div class="board">
      <div class="messages" id="messages"></div>
      <div class="controls">
        <input type="text" id="modInput" placeholder="Send moderator message..." />
        <button class="btn-send" onclick="sendModMessage()">Send</button>
        <button class="btn-halt" onclick="haltConference()">Halt</button>
      </div>
    </div>
  </div>

  <script>
    let ws = null;
    let currentRound = 0;

    function connect() {
      const proto = location.protocol === "https:" ? "wss:" : "ws:";
      ws = new WebSocket(`${proto}//${location.host}/ws`);

      ws.onopen = () => {
        document.getElementById("connDot").className = "dot dot-connected";
        document.getElementById("connText").textContent = "Connected";
      };

      ws.onclose = () => {
        document.getElementById("connDot").className = "dot dot-disconnected";
        document.getElementById("connText").textContent = "Reconnecting...";
        setTimeout(connect, 2000);
      };

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        handleEvent(data);
      };
    }

    function handleEvent(data) {
      const event = data.event;

      if (event === "initial_state") {
        document.getElementById("topic").textContent = data.topic;
        updateStatus(data.status);
        updateRound(data.current_round);
        renderAgents(data.agents);
        renderAllMessages(data.messages);
        return;
      }

      if (event === "agent_joined" || event === "agent_left" ||
          event === "agent_acted" || event === "round_started") {
        fetchAgents();
      }

      if (event === "round_started") {
        updateRound(data.round_number);
        addRoundSeparator(data.round_number);
      }

      if (event === "message_posted") {
        addMessage(data.agent_name, data.content, data.round_number, false);
      }

      if (event === "moderator_message") {
        addMessage("Moderator", data.content, currentRound, true);
      }

      if (event === "agent_acted" && data.action_type === "pass") {
        const el = document.createElement("div");
        el.className = "pass-notice";
        el.textContent = `Agent passed this round`;
        document.getElementById("messages").appendChild(el);
        scrollMessages();
      }

      if (event === "agent_acted" && data.action_type === "vote_to_end") {
        const el = document.createElement("div");
        el.className = "vote-notice";
        el.textContent = `An agent voted to end the conference`;
        document.getElementById("messages").appendChild(el);
        scrollMessages();
      }

      if (event === "conference_started") {
        updateStatus("active");
      }
      if (event === "conference_ended") {
        updateStatus("completed");
      }
      if (event === "conference_halted") {
        updateStatus("halted");
      }
    }

    function updateStatus(status) {
      const badge = document.getElementById("statusBadge");
      badge.textContent = status;
      badge.className = `status-badge status-${status}`;
    }

    function updateRound(num) {
      currentRound = num;
      document.getElementById("roundBadge").textContent = `Round: ${num || "-"}`;
    }

    function renderAgents(agents) {
      const container = document.getElementById("agentList");
      container.innerHTML = agents.map(a => `
        <div class="agent-card">
          <div class="name">${escapeHtml(a.name)}</div>
          ${a.role ? `<div class="role">${escapeHtml(a.role)}</div>` : ""}
          <span class="agent-status agent-status-${a.status}">${a.status}</span>
        </div>
      `).join("");
    }

    function renderAllMessages(messages) {
      const container = document.getElementById("messages");
      container.innerHTML = "";
      let lastRound = 0;
      for (const m of messages) {
        if (m.round_number !== lastRound) {
          lastRound = m.round_number;
          addRoundSeparator(lastRound);
        }
        addMessage(
          m.agent_name, m.content, m.round_number,
          m.agent_id === "moderator"
        );
      }
    }

    function addRoundSeparator(roundNum) {
      const el = document.createElement("div");
      el.className = "round-header";
      el.textContent = `Round ${roundNum}`;
      document.getElementById("messages").appendChild(el);
    }

    function addMessage(author, content, round, isModerator) {
      const el = document.createElement("div");
      el.className = `message${isModerator ? " moderator" : ""}`;
      el.innerHTML = `
        <div class="msg-header">
          <span class="msg-author">${escapeHtml(author)}</span>
          <span class="msg-time">Round ${round}</span>
        </div>
        <div class="msg-body">${escapeHtml(content)}</div>
      `;
      document.getElementById("messages").appendChild(el);
      scrollMessages();
    }

    function scrollMessages() {
      const el = document.getElementById("messages");
      el.scrollTop = el.scrollHeight;
    }

    async function fetchAgents() {
      try {
        const resp = await fetch("/api/agents");
        const agents = await resp.json();
        renderAgents(agents);
      } catch (e) { /* ignore */ }
    }

    function sendModMessage() {
      const input = document.getElementById("modInput");
      const content = input.value.trim();
      if (!content || !ws) return;
      ws.send(JSON.stringify({ type: "moderator_message", content }));
      input.value = "";
    }

    function haltConference() {
      if (!confirm("Halt the conference?")) return;
      if (ws) ws.send(JSON.stringify({ type: "halt", reason: "Halted by moderator" }));
    }

    function escapeHtml(text) {
      const div = document.createElement("div");
      div.textContent = text;
      return div.innerHTML;
    }

    document.getElementById("modInput").addEventListener("keydown", (e) => {
      if (e.key === "Enter") sendModMessage();
    });

    connect();
  </script>
</body>
</html>
```

**Step 2: Run the dashboard test again to verify HTML is served**

Run: `pytest tests/test_web.py::test_dashboard_serves_html -v`
Expected: PASS

**Step 3: Commit**

```bash
git add src/macf/web/static/index.html
git commit -m "feat: real-time browser dashboard with WebSocket updates"
```

---

### Task 8: Main Entry Point

**Files:**
- Create: `src/macf/main.py`

**Step 1: Create the main entry point**

This starts both the MCP server and the web dashboard on the same FastAPI app.

```python
# src/macf/main.py
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import uvicorn

from macf.web.app import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="MACF2 - Multi-Agent Conference Framework")
    parser.add_argument("--topic", default="Untitled Conference", help="Conference topic")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind to")
    parser.add_argument(
        "--workspace",
        default=None,
        help="Directory for shared files (default: temp dir)",
    )
    parser.add_argument(
        "--mcp-port",
        type=int,
        default=8001,
        help="Port for the MCP server (streamable HTTP)",
    )
    args = parser.parse_args()

    workspace = Path(args.workspace) if args.workspace else None
    app = create_app(topic=args.topic, workspace_dir=workspace)

    # Run MCP server in a background thread on a separate port
    mcp = app.state.mcp

    import threading
    import asyncio

    def run_mcp():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(
            mcp.run_async(transport="streamable-http", host=args.host, port=args.mcp_port)
        )

    mcp_thread = threading.Thread(target=run_mcp, daemon=True)
    mcp_thread.start()

    print(f"MACF2 Conference: {args.topic}")
    print(f"Dashboard: http://{args.host}:{args.port}")
    print(f"MCP Server: http://{args.host}:{args.mcp_port}/mcp")
    print()

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
```

**Step 2: Verify it imports cleanly**

Run: `python -c "from macf.main import main; print('OK')"`
Expected: OK

**Step 3: Commit**

```bash
git add src/macf/main.py
git commit -m "feat: main entry point starting dashboard and MCP server"
```

---

### Task 9: Integration Test

**Files:**
- Create: `tests/test_integration.py`

**Step 1: Write integration test**

This test starts a conference, registers agents, runs a full round, and verifies the state transitions work end-to-end.

```python
# tests/test_integration.py
import pytest
import json
from httpx import AsyncClient, ASGITransport
from macf.web.app import create_app
from macf.models import ConferenceStatus


@pytest.fixture
def app(tmp_path):
    return create_app(topic="Integration Test", workspace_dir=tmp_path)


@pytest.mark.asyncio
async def test_full_conference_flow(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Register 3 agents
        r1 = await client.post("/api/register", json={"name": "Architect", "role": "designs systems"})
        a1 = r1.json()["agent_id"]
        r2 = await client.post("/api/register", json={"name": "Developer", "role": "writes code"})
        a2 = r2.json()["agent_id"]
        r3 = await client.post("/api/register", json={"name": "Reviewer", "role": "reviews code"})
        a3 = r3.json()["agent_id"]

        # Start conference
        resp = await client.post("/api/start")
        assert resp.status_code == 200

        # Verify conference is active
        resp = await client.get("/api/conference")
        assert resp.json()["status"] == "active"
        assert resp.json()["current_round"] == 1

        # Agents are listed
        resp = await client.get("/api/agents")
        assert len(resp.json()) == 3


@pytest.mark.asyncio
async def test_file_operations_via_conference(app, tmp_path):
    conference = app.state.conference
    fm = app.state.file_manager

    # Create and manipulate files
    fm.create_file("design.md", "# Design\n")
    a1 = conference.register_agent("Writer")
    a2 = conference.register_agent("Editor")

    # Lock, write, release
    assert fm.acquire_lock("design.md", a1) is True
    fm.write_file("design.md", "# Updated Design\n", a1)
    assert fm.read_file("design.md") == "# Updated Design\n"

    # Other agent can't write
    with pytest.raises(PermissionError):
        fm.write_file("design.md", "nope", a2)

    # Release and other agent can now lock
    fm.release_lock("design.md", a1)
    assert fm.acquire_lock("design.md", a2) is True


@pytest.mark.asyncio
async def test_conference_completes_on_votes(app):
    conference = app.state.conference

    a1 = conference.register_agent("A1")
    a2 = conference.register_agent("A2")
    a3 = conference.register_agent("A3")
    conference.start()

    # Round 1: majority votes to end
    conference.vote_to_end(a1)
    conference.vote_to_end(a2)
    conference.post_message(a3, "I disagree but ok")

    assert conference.state.status == ConferenceStatus.COMPLETED


@pytest.mark.asyncio
async def test_moderator_can_halt(app):
    conference = app.state.conference

    a1 = conference.register_agent("A1")
    a2 = conference.register_agent("A2")
    conference.start()

    conference.halt("Going off the rails")
    assert conference.state.status == ConferenceStatus.HALTED
```

**Step 2: Run integration tests**

Run: `pytest tests/test_integration.py -v`
Expected: All PASS

**Step 3: Commit**

```bash
git add tests/test_integration.py
git commit -m "test: integration tests for full conference flow"
```

---

### Task 10: Final Verification

**Step 1: Run all tests**

Run: `pytest tests/ -v --tb=short`
Expected: All tests PASS

**Step 2: Verify the server starts**

Run: `timeout 5 python -m macf.main --topic "Test" || true`
Expected: Server prints startup messages (dashboard URL, MCP URL) before timing out

**Step 3: Final commit with any fixups**

```bash
git add -A
git commit -m "chore: final touches and cleanup"
```

---

## Summary of Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                    MACF2 Conference Server                    │
│                                                              │
│  ┌─────────────────┐     ┌─────────────────────────────┐    │
│  │   MCP Server     │     │   FastAPI Web Server         │    │
│  │   (port 8001)    │     │   (port 8000)                │    │
│  │                  │     │                              │    │
│  │  Tools:          │     │  REST:  /api/conference      │    │
│  │  - register      │     │         /api/agents          │    │
│  │  - post_message   │     │         /api/board           │    │
│  │  - pass_turn      │     │         /api/moderator/msg   │    │
│  │  - vote_to_end    │     │         /api/halt            │    │
│  │  - get_board      │     │                              │    │
│  │  - file ops       │     │  WS:    /ws (real-time)     │    │
│  └────────┬─────────┘     └──────────┬──────────────────┘    │
│           │                          │                        │
│           ▼                          ▼                        │
│  ┌─────────────────────────────────────────────────────┐     │
│  │              ConferenceManager                       │     │
│  │  - Agents, Rounds, Messages, State Machine          │     │
│  ├─────────────────────────────────────────────────────┤     │
│  │              FileManager                             │     │
│  │  - Shared files, exclusive write locks              │     │
│  └─────────────────────────────────────────────────────┘     │
└──────────────────────────────────────────────────────────────┘

    ▲               ▲               ▲              ▲
    │               │               │              │
 Agent 1         Agent 2         Agent 3       Browser
 (Claude)        (Codex)         (Claude)      Dashboard
 via MCP         via MCP         via MCP       via WS
```

## MCP Configuration for Agents

To connect an agent (e.g., Claude Code) to the conference, add to their MCP config:

```json
{
  "mcpServers": {
    "conference": {
      "url": "http://127.0.0.1:8001/mcp"
    }
  }
}
```

The agent can then use tools like `register_agent`, `post_message`, `get_board`, etc.
