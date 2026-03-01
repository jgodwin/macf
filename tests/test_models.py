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
