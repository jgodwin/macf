"""Generate markdown transcripts from completed conferences."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from macf2.models import ActionType, ConferenceState, ConferenceStatus


def generate_session_id(state: ConferenceState) -> str:
    """Generate a session ID in format YYYYMMDD-HHMMSS-xxxxxxxx.

    Timestamp comes from the first round's started_at if rounds exist,
    otherwise falls back to the current UTC time. The suffix is the
    first 8 characters of the conference state id.
    """
    if state.rounds:
        ts = state.rounds[0].started_at
    else:
        ts = datetime.now(timezone.utc)
    return ts.strftime("%Y%m%d-%H%M%S") + "-" + state.id[:8]


def write_transcript(state: ConferenceState, output_path: Path) -> bool:
    """Write a markdown transcript file for a conference.

    Returns True if the transcript was written, False if skipped
    (conference is still in WAITING status or has no rounds).
    """
    if state.status == ConferenceStatus.WAITING or not state.rounds:
        return False

    lines: list[str] = []

    # Header
    lines.append("# Conference Transcript")
    lines.append("")
    lines.append(f"**Topic:** {state.topic}")
    lines.append(f"**Goal:** {state.goal}")
    lines.append(f"**Status:** {state.status.value}")
    lines.append(f"**Session ID:** {state.id}")
    lines.append(f"**Started:** {state.rounds[0].started_at.isoformat()}")

    last_round = state.rounds[-1]
    if last_round.ended_at is not None:
        lines.append(f"**Ended:** {last_round.ended_at.isoformat()}")
    else:
        lines.append("**Ended:** In progress")

    lines.append("")

    # Participants table
    lines.append("## Participants")
    lines.append("")
    lines.append("| Agent ID | Name | Role |")
    lines.append("|----------|------|------|")
    for agent_id, agent_info in state.agents.items():
        short_id = agent_id[:8]
        lines.append(f"| {short_id} | {agent_info.name} | {agent_info.role} |")
    lines.append("")

    # Rounds
    total_messages = 0

    for rnd in state.rounds:
        lines.append(f"## Round {rnd.number}")
        lines.append("")

        # Collect all entries for this round: agent actions + moderator messages
        entries: list[tuple[datetime, str]] = []

        # Agent actions sorted by timestamp
        sorted_actions = sorted(rnd.actions.values(), key=lambda a: a.timestamp)
        for action in sorted_actions:
            agent_id = action.agent_id
            short_id = agent_id[:8]

            # Look up agent name and role
            if agent_id in state.agents:
                agent_name = state.agents[agent_id].name
            else:
                agent_name = agent_id

            if action.type == ActionType.MESSAGE:
                total_messages += 1
                entry = f"### {agent_name} ({short_id}) — message\n\n{action.content}\n"
                entries.append((action.timestamp, entry))
            elif action.type == ActionType.PASS:
                entry = f"### {agent_name} ({short_id}) — pass\n"
                entries.append((action.timestamp, entry))
            elif action.type == ActionType.VOTE_TO_END:
                entry = f"### {agent_name} ({short_id}) — vote_to_end\n"
                entries.append((action.timestamp, entry))

        # Include moderator messages for this round
        for msg in state.messages:
            if msg.agent_id == "moderator" and msg.round_number == rnd.number:
                entry = f"### {msg.agent_name} (moderato) — message\n\n{msg.content}\n"
                entries.append((msg.timestamp, entry))

        # Sort all entries chronologically
        entries.sort(key=lambda e: e[0])

        for _, entry_text in entries:
            lines.append(entry_text)

        lines.append("---")
        lines.append("")

    # Summary
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- **Total rounds:** {len(state.rounds)}")
    lines.append(f"- **Total messages:** {total_messages}")
    lines.append(f"- **Outcome:** {state.status.value}")
    lines.append("")

    content = "\n".join(lines)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content)

    return True


def write_config(state: ConferenceState, roles: list, output_path: Path) -> bool:
    """Write conference configuration to a JSON file.

    Produces the same format as ConferenceConfig, loadable via --config.
    Returns True if written, False if skipped (no topic configured).
    """
    if not state.topic:
        return False

    config = {
        "topic": state.topic,
        "goal": state.goal,
        "roles": [
            {"name": r.name, "description": r.description, "instructions": r.instructions}
            for r in roles
        ],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(config, indent=2) + "\n")
    return True
