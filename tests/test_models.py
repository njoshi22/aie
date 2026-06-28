from core.models import Memory, Agent, PermissionTier, MemoryType


def test_memory_defaults():
    m = Memory(session_id="s1", agent_id="a1",
               type=MemoryType.PRICING_FIELD_RULE, content="check the schedule")
    assert m.relevance_score == 0.5
    assert m.access_count == 0
    assert m.sessions_since_used == 0
    assert m.last_used_at is None
    assert isinstance(m.id, str) and len(m.id) > 0
    assert m.embedding == []


def test_agent_defaults():
    a = Agent(name="RevOps Agent")
    assert a.reputation_score == 0.1
    assert a.permission_tier == PermissionTier.OBSERVER
    assert a.total_sessions == 0
