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


class RoleConfig(BaseModel):
    """Pre-defined role slot that agents can claim when registering."""
    name: str
    description: str = ""
    instructions: str = ""


class ConferenceConfig(BaseModel):
    """Full conference configuration, loadable from a JSON file."""
    topic: str
    goal: str = ""
    roles: list[RoleConfig] = Field(default_factory=list)


class ConferenceState(BaseModel):
    id: str = Field(default_factory=_uuid)
    topic: str
    goal: str = ""
    status: ConferenceStatus = ConferenceStatus.WAITING
    agents: dict[str, AgentInfo] = Field(default_factory=dict)
    rounds: list[Round] = Field(default_factory=list)
    messages: list[Message] = Field(default_factory=list)
    moderator_messages: list[Message] = Field(default_factory=list)
    current_round: int = 0
