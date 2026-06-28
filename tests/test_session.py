from core import database, session
from core.models import Agent, Memory, MemoryType


def test_complete_bumps_used_memory_on_success(conn):
    a = Agent(name="A")
    database.insert_agent(conn, a)
    s = session.start(conn, a.id, task="reconcile")
    m = Memory(session_id=s.id, agent_id=a.id, type=MemoryType.PRICING_FIELD_RULE,
               content="schedule", relevance_score=0.5)
    database.insert_memory(conn, m)
    session.set_memories(conn, s.id, used=[m.id], created=[])
    done, agent = session.complete(conn, s.id, {"accuracy": 1.0})
    assert done.status == "completed"
    assert database.get_memory(conn, m.id).relevance_score == 0.6
    assert agent.total_sessions == 1


def test_complete_failure_decrements(conn):
    a = Agent(name="A")
    database.insert_agent(conn, a)
    s = session.start(conn, a.id, task="reconcile")
    m = Memory(session_id=s.id, agent_id=a.id, type=MemoryType.PRICING_FIELD_RULE,
               content="x", relevance_score=0.5)
    database.insert_memory(conn, m)
    session.set_memories(conn, s.id, used=[m.id], created=[])
    done, _ = session.complete(conn, s.id, {"accuracy": 0.0})
    assert done.status == "failed"
    assert abs(database.get_memory(conn, m.id).relevance_score - 0.45) < 1e-9


def test_unused_memory_decays_after_three_idle_sessions(conn):
    a = Agent(name="A")
    database.insert_agent(conn, a)
    used = Memory(session_id="s", agent_id=a.id, type=MemoryType.PRICING_FIELD_RULE,
                  content="used", relevance_score=0.5)
    idle = Memory(session_id="s", agent_id=a.id, type=MemoryType.CONTRACT_TERM,
                  content="idle", relevance_score=0.5)
    database.insert_memory(conn, used)
    database.insert_memory(conn, idle)
    for _ in range(3):
        s = session.start(conn, a.id, task="reconcile")
        session.set_memories(conn, s.id, used=[used.id], created=[])
        session.complete(conn, s.id, {"accuracy": 1.0})
    # used 3x: 0.5 + 0.1*3 = 0.8; idle decays once on the 3rd idle session: 0.5 * 0.95
    assert abs(database.get_memory(conn, used.id).relevance_score - 0.8) < 1e-9
    got_idle = database.get_memory(conn, idle.id)
    assert got_idle.sessions_since_used == 3
    assert abs(got_idle.relevance_score - 0.475) < 1e-9
