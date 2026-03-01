import pytest
from macf2.conference import ConferenceManager
from macf2.models import ConferenceStatus, ActionType, AgentStatus, RoleConfig


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


def test_briefing_includes_topic_and_protocol(conf):
    a1 = conf.register_agent("Architect", role="system designer")
    briefing = conf.get_briefing(a1)
    assert "Design a REST API" in briefing
    assert "Architect" in briefing
    assert "system designer" in briefing
    assert "ROUND PROTOCOL" in briefing
    assert "post_message" in briefing


def test_briefing_includes_goal():
    conf = ConferenceManager(topic="API Design", goal="Produce an OpenAPI spec")
    a1 = conf.register_agent("Architect")
    briefing = conf.get_briefing(a1)
    assert "Produce an OpenAPI spec" in briefing


def test_briefing_shows_other_participants(conf):
    a1 = conf.register_agent("Architect", role="designs systems")
    a2 = conf.register_agent("Developer", role="writes code")
    briefing = conf.get_briefing(a1)
    assert "Developer" in briefing
    assert "writes code" in briefing


def test_role_configs_applied_on_register():
    roles = [
        RoleConfig(name="Architect", description="system designer", instructions="Focus on structure"),
        RoleConfig(name="Developer", description="coder", instructions="Write clean code"),
    ]
    conf = ConferenceManager(topic="Test", roles=roles)
    a1 = conf.register_agent("Architect")
    agent = conf.state.agents[a1]
    assert agent.role == "system designer"
    assert agent.instructions == "Focus on structure"


def test_available_roles():
    roles = [
        RoleConfig(name="Architect", description="system designer"),
        RoleConfig(name="Developer", description="coder"),
    ]
    conf = ConferenceManager(topic="Test", roles=roles)
    avail = conf.get_available_roles()
    assert len(avail) == 2
    conf.register_agent("Architect")
    avail = conf.get_available_roles()
    assert len(avail) == 1
    assert avail[0]["name"] == "Developer"
