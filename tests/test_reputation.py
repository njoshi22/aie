from core import database, reputation, session
from core.models import Agent, PermissionTier


def test_tier_boundaries():
    assert reputation.tier_for(0.0) == PermissionTier.OBSERVER
    assert reputation.tier_for(0.29) == PermissionTier.OBSERVER
    assert reputation.tier_for(0.3) == PermissionTier.ANALYST
    assert reputation.tier_for(0.59) == PermissionTier.ANALYST
    assert reputation.tier_for(0.6) == PermissionTier.AUTONOMOUS


def _run(conn, agent_id, accuracy):
    s = session.start(conn, agent_id, task="reconcile")
    session.complete(conn, s.id, {"accuracy": accuracy})


def test_demo_trajectory(conn):
    a = Agent(name="A")
    database.insert_agent(conn, a)
    _run(conn, a.id, 0.0)   # S1 cold: miss
    assert database.get_agent(conn, a.id).permission_tier == PermissionTier.OBSERVER
    _run(conn, a.id, 1.0)   # S2: correct
    assert database.get_agent(conn, a.id).permission_tier == PermissionTier.ANALYST
    _run(conn, a.id, 1.0)   # S3: correct
    assert database.get_agent(conn, a.id).permission_tier == PermissionTier.AUTONOMOUS
