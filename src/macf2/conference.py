from __future__ import annotations

import asyncio
from typing import Any, Callable, Coroutine

from macf2.models import (
    ActionType,
    AgentInfo,
    AgentStatus,
    ConferenceConfig,
    ConferenceState,
    ConferenceStatus,
    Message,
    RoleConfig,
    Round,
    RoundAction,
    RoundStatus,
)


PROTOCOL_INSTRUCTIONS = """\
You are participating in a structured multi-agent conference. Follow this protocol:

ROUND PROTOCOL:
- The conference proceeds in rounds. Each round, every agent must take exactly one action.
- Your options each round: post_message (share your thoughts), pass_turn (skip), or vote_to_end (signal you're done).
- A round completes when ALL agents have acted. Then the next round begins automatically.
- If a majority of agents vote_to_end in the same round, the conference concludes.

WORKFLOW:
1. Call register_agent with your assigned name and role to join the conference.
2. Call get_board to read all previous messages before responding.
3. Call get_round_info to see who has acted and who is pending this round.
4. Take your action: post_message, pass_turn, or vote_to_end.
5. After acting, wait and poll get_round_info or get_conference_status until the next round starts.
6. Repeat from step 2.

COLLABORATION:
- Read what others have posted before responding. Build on their ideas.
- Be concise and focused. Address the goal directly.
- When working on shared files, use acquire_file_lock before writing and release_file_lock when done.
- Vote to end only when the goal has been achieved or no further progress can be made.
"""


class ConferenceManager:
    def __init__(self, topic: str, goal: str = "", roles: list[RoleConfig] | None = None):
        self.state = ConferenceState(topic=topic, goal=goal)
        self._roles = roles or []
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
        # If a matching pre-defined role exists, inherit its description and instructions
        for rc in self._roles:
            if rc.name == name:
                role = role or rc.description
                instructions = instructions or rc.instructions
                break
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
        from macf2.models import _now
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

    def get_available_roles(self) -> list[dict]:
        """Return pre-defined roles that haven't been claimed yet."""
        claimed_names = {
            a.name for a in self.state.agents.values()
            if a.status != AgentStatus.DISCONNECTED
        }
        return [
            {"name": rc.name, "description": rc.description}
            for rc in self._roles
            if rc.name not in claimed_names
        ]

    def get_briefing(self, agent_id: str) -> str:
        """Build the full briefing text for a specific agent."""
        agent = self.state.agents.get(agent_id)
        if not agent:
            raise ValueError(f"Unknown agent: {agent_id}")

        parts = [
            f"# Conference Briefing",
            f"",
            f"## Topic",
            f"{self.state.topic}",
        ]

        if self.state.goal:
            parts += [
                f"",
                f"## Goal",
                f"{self.state.goal}",
            ]

        parts += [
            f"",
            f"## Your Role",
            f"**Name:** {agent.name}",
        ]
        if agent.role:
            parts.append(f"**Role:** {agent.role}")
        if agent.instructions:
            parts += [
                f"",
                f"### Your Specific Instructions",
                f"{agent.instructions}",
            ]

        # Show who else is at the table
        other_agents = [
            a for a in self.state.agents.values()
            if a.id != agent_id and a.status != AgentStatus.DISCONNECTED
        ]
        if other_agents:
            parts += [
                f"",
                f"## Other Participants",
            ]
            for a in other_agents:
                role_text = f" - {a.role}" if a.role else ""
                parts.append(f"- **{a.name}**{role_text}")

        parts += [
            f"",
            f"## Protocol",
            PROTOCOL_INSTRUCTIONS,
        ]

        return "\n".join(parts)
