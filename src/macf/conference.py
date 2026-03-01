from __future__ import annotations

import asyncio
from typing import Any, Callable, Coroutine

from macf.models import (
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

TURN ORDER:
- Round 1 is parallel: all agents may act in any order.
- Round 2 and beyond use round-robin turn taking: agents act one at a time in a fixed order.
- Call get_round_info() to see the turn_order and current_turn fields to know whose turn it is.
- If it is not your turn, wait and poll get_round_info() until current_turn shows your name.

WORKFLOW:
1. Call register_agent with your assigned name and role to join the conference.
2. Call get_board to read all previous messages before responding.
3. Call get_round_info to see the turn order and whose turn it is.
4. If it is your turn, take your action: post_message, pass_turn, or vote_to_end.
5. If it is not your turn, wait and poll get_round_info until it is.
6. After acting, wait and poll get_round_info or get_conference_status until the next round starts.
7. Repeat from step 2.

COLLABORATION:
- Read what others have posted before responding. Build on their ideas.
- Be concise and focused. Address the goal directly.
- When working on shared files, use acquire_file_lock before writing and release_file_lock when done.
- Vote to end only when the goal has been achieved or no further progress can be made.
"""


class ConferenceManager:
    def __init__(self, topic: str = "", goal: str = "", roles: list[RoleConfig] | None = None):
        self.state = ConferenceState(topic=topic, goal=goal)
        self._roles = roles or []
        self._event_listeners: list[Callable[[str, dict], Coroutine]] = []
        self._configured = asyncio.Event()
        self._turn_order: list[str] = []
        self._current_turn_index: int = 0
        if topic:  # Already configured at construction time
            self._configured.set()

    async def wait_for_configuration(self) -> None:
        """Block until the conference has been configured with a topic."""
        await self._configured.wait()

    @property
    def is_configured(self) -> bool:
        return self._configured.is_set()

    def on_event(self, callback: Callable[[str, dict], Coroutine]) -> None:
        self._event_listeners.append(callback)

    def configure(self, topic: str, goal: str = "", roles: list[RoleConfig] | None = None) -> None:
        """Set or update conference topic, goal, and roles. Only valid before start."""
        if self.state.status != ConferenceStatus.WAITING:
            raise ValueError("Cannot reconfigure after conference has started")
        self.state.topic = topic
        self.state.goal = goal
        self._roles = roles or []
        self._configured.set()
        self._emit("conference_configured", {
            "topic": topic, "goal": goal,
            "roles": [{"name": r.name, "description": r.description} for r in self._roles],
        })

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
        # Handle disconnection mid-turn in round-robin mode
        if (self.state.status == ConferenceStatus.ACTIVE
                and self.state.current_round > 1
                and self._turn_order
                and self._current_turn_index < len(self._turn_order)
                and self._turn_order[self._current_turn_index] == agent_id):
            current = self._current_round()
            active = self._active_agent_ids()
            if current.all_acted(active):
                self._check_round_complete()
            elif current.status == RoundStatus.ACTIVE:
                self._advance_to_next_active_turn()
                if self._current_turn_index < len(self._turn_order):
                    next_id = self._turn_order[self._current_turn_index]
                    if next_id in active:
                        self.state.agents[next_id].status = AgentStatus.THINKING
                        self._emit("turn_started", {
                            "agent_id": next_id,
                            "agent_name": self.state.agents[next_id].name,
                            "round_number": current.number,
                        })

    def start(self) -> None:
        active = self._active_agent_ids()
        if len(active) < 2:
            raise ValueError("Need at least 2 agents to start")
        self.state.status = ConferenceStatus.ACTIVE
        self._turn_order = [aid for aid in self.state.agents if aid in active]
        self._start_new_round()
        self._emit("conference_started", {"topic": self.state.topic})

    def _start_new_round(self) -> None:
        self.state.current_round += 1
        new_round = Round(number=self.state.current_round)
        self.state.rounds.append(new_round)
        self._current_turn_index = 0
        active = self._active_agent_ids()

        if self.state.current_round == 1:
            # Round 1: parallel — all agents think at once
            for aid in active:
                self.state.agents[aid].status = AgentStatus.THINKING
            self._emit("round_started", {"round_number": self.state.current_round})
        else:
            # Round 2+: round-robin turn taking
            self._advance_to_next_active_turn()
            for aid in active:
                if (self._current_turn_index < len(self._turn_order)
                        and aid == self._turn_order[self._current_turn_index]):
                    self.state.agents[aid].status = AgentStatus.THINKING
                else:
                    self.state.agents[aid].status = AgentStatus.CONNECTED
            active_turn_order = [
                self.state.agents[aid].name
                for aid in self._turn_order
                if aid in active
            ]
            current_turn_name = (
                self.state.agents[self._turn_order[self._current_turn_index]].name
                if self._current_turn_index < len(self._turn_order)
                else None
            )
            self._emit("round_started", {
                "round_number": self.state.current_round,
                "turn_order": active_turn_order,
                "current_turn": current_turn_name,
            })

    def _advance_to_next_active_turn(self) -> None:
        """Skip disconnected agents by incrementing _current_turn_index."""
        active = self._active_agent_ids()
        attempts = 0
        while (self._current_turn_index < len(self._turn_order)
               and self._turn_order[self._current_turn_index] not in active):
            self._current_turn_index += 1
            attempts += 1
            if attempts >= len(self._turn_order):
                break

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
        # Enforce turn order for rounds > 1
        if self.state.current_round > 1:
            expected_id = self._turn_order[self._current_turn_index]
            if agent_id != expected_id:
                expected_name = self.state.agents[expected_id].name
                agent_name = self.state.agents[agent_id].name
                raise ValueError(f"Not your turn. It is {expected_name}'s turn, not {agent_name}'s.")
        current.actions[agent_id] = action
        self.state.agents[agent_id].status = AgentStatus.ACTED
        self._emit("agent_acted", {
            "agent_id": agent_id,
            "agent_name": self.state.agents[agent_id].name,
            "action_type": action.type.value,
            "round_number": current.number,
        })
        if self.state.current_round > 1:
            self._advance_after_action()
        else:
            self._check_round_complete()

    def post_message(self, agent_id: str, content: str) -> bool:
        agent = self.state.agents[agent_id]
        round_number = self.state.current_round
        msg = Message(
            agent_id=agent_id,
            agent_name=agent.name,
            round_number=round_number,
            content=content,
        )
        self.state.messages.append(msg)
        self._emit("message_posted", {
            "agent_id": agent_id,
            "agent_name": agent.name,
            "content": content,
            "round_number": round_number,
        })
        self._record_action(
            agent_id,
            RoundAction(agent_id=agent_id, type=ActionType.MESSAGE, content=content),
        )
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

    def _advance_after_action(self) -> None:
        """After an agent acts in round-robin mode, advance to next turn or complete round."""
        active = self._active_agent_ids()
        current = self._current_round()
        self._current_turn_index += 1
        if current.all_acted(active):
            current.status = RoundStatus.COMPLETED
            from macf.models import _now
            current.ended_at = _now()
            votes = current.end_vote_count()
            if votes > len(active) / 2:
                self.state.status = ConferenceStatus.COMPLETED
                self._emit("conference_ended", {"reason": "majority_vote"})
            else:
                self._start_new_round()
        else:
            self._advance_to_next_active_turn()
            if self._current_turn_index < len(self._turn_order):
                next_id = self._turn_order[self._current_turn_index]
                self.state.agents[next_id].status = AgentStatus.THINKING
                self._emit("turn_started", {
                    "agent_id": next_id,
                    "agent_name": self.state.agents[next_id].name,
                    "round_number": current.number,
                })

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

    def reset(self) -> None:
        """Reset all state back to a fresh conference."""
        old_state = self.state
        self.state = ConferenceState(topic="", goal="")
        self._roles = []
        self._configured = asyncio.Event()
        self._turn_order = []
        self._current_turn_index = 0
        self._emit("conference_reset", {"old_state": old_state})

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
        result = {
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
        if current.number > 1 and self._turn_order:
            active_turn_order = [
                self.state.agents[aid].name
                for aid in self._turn_order
                if aid in active
            ]
            result["turn_order"] = active_turn_order
            if current.status == RoundStatus.ACTIVE and self._current_turn_index < len(self._turn_order):
                result["current_turn"] = self.state.agents[self._turn_order[self._current_turn_index]].name
            else:
                result["current_turn"] = None
        return result

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

**Round 1** is parallel: all agents may act in any order.

**Round 2+** uses round-robin turn taking: agents act one at a time in a fixed order.
Call `get_round_info()` to see `turn_order` and `current_turn`. If it is not your turn, wait and poll `get_round_info()` until `current_turn` shows your name.

Before acting each round:
- Call `get_board()` to read what others have posted.
- Call `get_round_info()` to check whose turn it is.

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
