from __future__ import annotations

import sqlite3

from core import database
from core.models import Agent, PermissionTier

SUCCESS_THRESHOLD = 0.5
INITIAL_REPUTATION_FLOOR = 0.1
MAX_REPUTATION_STEP = 0.25


def tier_for(score: float) -> str:
    if score < 0.3:
        return PermissionTier.OBSERVER
    if score < 0.6:
        return PermissionTier.ANALYST
    return PermissionTier.AUTONOMOUS


def compute(success_rate: float, avg_accuracy: float) -> float:
    return max(0.0, min(1.0, 0.6 * success_rate + 0.4 * avg_accuracy))


def _bounded_score(previous: float, target: float) -> float:
    delta = max(-MAX_REPUTATION_STEP, min(MAX_REPUTATION_STEP, target - previous))
    return max(INITIAL_REPUTATION_FLOOR, min(1.0, round(previous + delta, 3)))


def update_after_session(conn: sqlite3.Connection, agent_id: str) -> Agent:
    agent = database.get_agent(conn, agent_id)
    if agent is None:
        raise ValueError(f"unknown agent {agent_id}")
    completed = [
        s for s in database.list_sessions(conn, agent_id)
        if s.status in ("completed", "failed") and s.outcome is not None
    ]
    accuracies = [float(s.outcome.get("accuracy", 0.0)) for s in completed if s.outcome is not None]
    total = len(completed)
    successful = sum(1 for x in accuracies if x >= SUCCESS_THRESHOLD)
    avg_accuracy = sum(accuracies) / total if total else 0.0
    success_rate = successful / total if total else 0.0

    agent.total_sessions = total
    agent.successful_sessions = successful
    target_score = compute(success_rate, avg_accuracy)
    agent.reputation_score = _bounded_score(agent.reputation_score, target_score)
    agent.permission_tier = tier_for(agent.reputation_score)
    database.update_agent(conn, agent)
    return agent
