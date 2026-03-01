import pytest
from macf.conference import ConferenceManager
from macf.models import ConferenceStatus, ActionType, AgentStatus, RoleConfig


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


def test_is_configured_flag():
    conf = ConferenceManager()
    assert conf.is_configured is False
    conf.configure(topic="Test")
    assert conf.is_configured is True


def test_is_configured_when_topic_at_init():
    conf = ConferenceManager(topic="Already set")
    assert conf.is_configured is True


@pytest.mark.asyncio
async def test_wait_for_configuration_blocks_then_resolves():
    import asyncio
    conf = ConferenceManager()
    resolved = False

    async def waiter():
        nonlocal resolved
        await conf.wait_for_configuration()
        resolved = True

    task = asyncio.create_task(waiter())
    await asyncio.sleep(0.05)
    assert resolved is False  # Still blocking

    conf.configure(topic="Now configured")
    await asyncio.sleep(0.05)
    assert resolved is True  # Unblocked
    await task


def test_round1_allows_any_order(conf):
    """Round 1 should allow agents to act in any order (parallel)."""
    a1 = conf.register_agent("A1")
    a2 = conf.register_agent("A2")
    a3 = conf.register_agent("A3")
    conf.start()
    # Any agent can act first in round 1
    conf.post_message(a3, "I go first")
    conf.post_message(a1, "I go second")
    conf.pass_turn(a2)
    # Round should advance
    assert conf.state.current_round == 2


def test_round2_enforces_turn_order(conf):
    """Round 2+ should enforce round-robin turn taking."""
    a1 = conf.register_agent("A1")
    a2 = conf.register_agent("A2")
    conf.start()
    # Complete round 1 (any order)
    conf.post_message(a1, "round 1")
    conf.pass_turn(a2)
    # Now in round 2 -- turn order is [a1, a2] (registration order)
    assert conf.state.current_round == 2
    # a2 should NOT be able to act before a1
    with pytest.raises(ValueError, match="Not your turn"):
        conf.post_message(a2, "out of turn")
    # a1 acts first
    conf.post_message(a1, "my turn")
    # Now a2 can act
    conf.post_message(a2, "my turn now")
    assert conf.state.current_round == 3


def test_round2_turn_order_matches_registration(conf):
    """Turn order should match the order agents registered."""
    a1 = conf.register_agent("A1")
    a2 = conf.register_agent("A2")
    a3 = conf.register_agent("A3")
    conf.start()
    # Complete round 1
    conf.post_message(a1, "r1")
    conf.post_message(a2, "r1")
    conf.post_message(a3, "r1")
    # Round 2: must go a1 -> a2 -> a3
    assert conf.state.current_round == 2
    conf.post_message(a1, "r2 first")
    with pytest.raises(ValueError, match="Not your turn"):
        conf.post_message(a3, "skip a2")
    conf.post_message(a2, "r2 second")
    conf.post_message(a3, "r2 third")
    assert conf.state.current_round == 3


def test_get_round_info_includes_turn_info(conf):
    """get_round_info should include turn_order and current_turn for round 2+."""
    a1 = conf.register_agent("A1")
    a2 = conf.register_agent("A2")
    conf.start()
    # Round 1: no turn info
    info = conf.get_round_info()
    assert "current_turn" not in info
    # Complete round 1
    conf.post_message(a1, "r1")
    conf.pass_turn(a2)
    # Round 2: should have turn info
    info = conf.get_round_info()
    assert info["turn_order"] == ["A1", "A2"]
    assert info["current_turn"] == "A1"
    # After a1 acts, current_turn should be a2
    conf.post_message(a1, "r2")
    info = conf.get_round_info()
    assert info["current_turn"] == "A2"


def test_pass_turn_advances_round_robin(conf):
    """pass_turn should work the same as post_message for turn advancement."""
    a1 = conf.register_agent("A1")
    a2 = conf.register_agent("A2")
    conf.start()
    conf.pass_turn(a1)
    conf.pass_turn(a2)
    # Round 2
    assert conf.state.current_round == 2
    conf.pass_turn(a1)  # a1's turn
    conf.pass_turn(a2)  # a2's turn
    assert conf.state.current_round == 3


def test_vote_to_end_respects_turn_order(conf):
    """vote_to_end should also respect round-robin in round 2+."""
    a1 = conf.register_agent("A1")
    a2 = conf.register_agent("A2")
    conf.start()
    conf.pass_turn(a1)
    conf.pass_turn(a2)
    # Round 2
    with pytest.raises(ValueError, match="Not your turn"):
        conf.vote_to_end(a2)
    conf.vote_to_end(a1)
    conf.vote_to_end(a2)
    assert conf.state.status == ConferenceStatus.COMPLETED


def test_disconnected_agent_skipped_in_turn_order(conf):
    """If an agent disconnects, they should be skipped in the turn order."""
    a1 = conf.register_agent("A1")
    a2 = conf.register_agent("A2")
    a3 = conf.register_agent("A3")
    conf.start()
    # Complete round 1
    conf.post_message(a1, "r1")
    conf.post_message(a2, "r1")
    conf.post_message(a3, "r1")
    # Round 2: disconnect a1 (who would be first)
    conf.unregister_agent(a1)
    # a2 should now be the current turn (a1 skipped)
    info = conf.get_round_info()
    assert info["current_turn"] == "A2"
    conf.post_message(a2, "r2")
    conf.post_message(a3, "r2")
    assert conf.state.current_round == 3


# --- MCP client tracking tests ---

def test_track_mcp_client_new(conf):
    """New client_id creates an McpClient and emits client_connected event."""
    events = []
    async def listener(event_type, data):
        events.append((event_type, data))
    conf.on_event(listener)
    conf.track_mcp_client("client-abc")
    assert "client-abc" in conf._mcp_clients
    assert conf._mcp_clients["client-abc"].agent_id is None
    assert any(e[0] == "client_connected" for e in events)


def test_track_mcp_client_duplicate(conf):
    """Tracking the same client_id twice is idempotent."""
    events = []
    async def listener(event_type, data):
        events.append((event_type, data))
    conf.on_event(listener)
    conf.track_mcp_client("client-abc")
    conf.track_mcp_client("client-abc")
    connected_events = [e for e in events if e[0] == "client_connected"]
    assert len(connected_events) == 1


def test_track_mcp_client_empty_id(conf):
    """Empty client_id is ignored."""
    conf.track_mcp_client("")
    assert len(conf._mcp_clients) == 0


def test_mcp_client_linked_on_register(conf):
    """After register_agent with client_id, McpClient.agent_id is set."""
    conf.track_mcp_client("client-xyz")
    agent_id = conf.register_agent("Alice", client_id="client-xyz")
    assert conf._mcp_clients["client-xyz"].agent_id == agent_id


def test_pending_clients_in_agents_info(conf):
    """Unlinked MCP clients appear in get_agents_info with status 'pending'."""
    conf.track_mcp_client("client-111")
    info = conf.get_agents_info()
    pending = [a for a in info if a["status"] == "pending"]
    assert len(pending) == 1
    assert pending[0]["id"] == "client-111"
    assert "client-111" in pending[0]["name"]


def test_linked_clients_not_pending(conf):
    """Linked MCP clients don't appear as separate pending entries."""
    conf.track_mcp_client("client-222")
    conf.register_agent("Bob", client_id="client-222")
    info = conf.get_agents_info()
    pending = [a for a in info if a["status"] == "pending"]
    assert len(pending) == 0
    # Bob should appear as a regular agent
    agents = [a for a in info if a["name"] == "Bob"]
    assert len(agents) == 1


def test_reset_clears_mcp_clients(conf):
    """reset() clears _mcp_clients."""
    conf.track_mcp_client("client-333")
    conf.reset()
    assert len(conf._mcp_clients) == 0
