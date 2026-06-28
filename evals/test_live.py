"""Tests for reading REAL persisted outcomes and summarizing them.

Builds a throwaway SQLite store via the real core engine, completes two sessions
(a failed cold start + a successful learned run), then reads them back through the
same path the CLI/harness use. Run: python -m pytest evals/test_live.py
"""

from __future__ import annotations

from pathlib import Path

from core import database, session
from core.models import Agent
from evals import live
from evals.scorecard import summarize_sessions


def _make_db(tmp_path: Path):
    conn = database.get_connection(tmp_path / "live.db")
    database.init_db(conn)
    agent = Agent(name="eval-agent")
    database.insert_agent(conn, agent)
    return conn, agent


def test_live_db_reads_failed_and_completed_sessions(tmp_path):
    conn, agent = _make_db(tmp_path)
    # S1 cold start fails (accuracy below threshold) - must still appear in the curve.
    s1 = session.start(conn, agent.id, "reconcile acme")
    session.complete(conn, s1.id, {"accuracy": 0.0, "material_caught": 0,
                                   "material_total": 1, "false_escalations": 1})
    # S2 learned succeeds.
    s2 = session.start(conn, agent.id, "reconcile acme")
    session.complete(conn, s2.id, {"accuracy": 1.0, "material_caught": 1,
                                   "material_total": 1, "false_escalations": 0})
    conn.close()

    outcomes = live.read_outcomes_from_db(db_path=str(tmp_path / "live.db"), agent_id=agent.id)
    assert len(outcomes) == 2                      # failed S1 included, not dropped
    assert [o["status"] for o in outcomes] == ["failed", "completed"]

    summary = summarize_sessions(outcomes)
    assert summary["n"] == 2
    assert summary["curve"][0]["accuracy"] == 0.0
    assert summary["curve"][1]["accuracy"] == 1.0
    assert summary["improved"] is True
    assert summary["deltas"]["false_escalations"] == -1


def test_live_summary_tags_source(tmp_path):
    conn, agent = _make_db(tmp_path)
    s = session.start(conn, agent.id, "t")
    session.complete(conn, s.id, {"accuracy": 1.0})
    conn.close()
    summary = live.live_summary(source="db", db_path=str(tmp_path / "live.db"))
    assert summary["source"] == "live-db"
    assert summary["n"] == 1
