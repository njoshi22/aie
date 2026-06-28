"""Optimizer tests.

The fallback path is exercised deterministically by injecting a client whose
model call raises, which forces ``optimize_skill`` down its canned branch
regardless of whether GEMINI_API_KEY is set in the environment.
"""

from __future__ import annotations

import tempfile

import pytest

from core import database, optimizer, reputation
from data.seed import seed


class _RaisingModels:
    def generate_content(self, **_kwargs):
        raise RuntimeError("simulated model outage")


class _RaisingClient:
    def __init__(self):
        self.models = _RaisingModels()


@pytest.fixture()
def conn():
    c = database.get_connection(tempfile.mktemp(suffix=".db"))
    database.init_db(c)
    return c


def test_fallback_recovers_skill_and_reputation(conn):
    agent = seed(conn)
    agent.reputation_score = 0.25  # tanked / locked
    agent.permission_tier = "observer"
    database.update_agent(conn, agent)

    res = optimizer.optimize_skill(conn, agent.id, client=_RaisingClient())

    assert res.fallback is True
    assert res.accepted is True
    assert res.new_score > res.base_score
    # a new active skill version was written, and it is the strong skill
    active = database.get_active_skill(conn, agent.id)
    assert active.version == res.new_version
    assert "ramp schedule" in active.content
    # reputation recovered above the production floor -> unlocked
    after = database.get_agent(conn, agent.id)
    assert after.reputation_score >= reputation.PRODUCTION_FLOOR
    assert res.reputation_after == after.reputation_score


def test_set_reputation_from_eval_moves_tier(conn):
    agent = seed(conn)
    low = reputation.set_reputation_from_eval(conn, agent.id, 0.0)
    assert low.permission_tier == "observer"
    high = reputation.set_reputation_from_eval(conn, agent.id, 0.95, max_step=1.0)
    assert high.reputation_score > low.reputation_score
    assert high.permission_tier in ("analyst", "autonomous")
