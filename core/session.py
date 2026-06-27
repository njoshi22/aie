from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any

from core import database, reputation
from core.models import Agent, Session

SUCCESS_THRESHOLD = 0.5
IDLE_DECAY_SESSIONS = 3
IDLE_DECAY_FACTOR = 0.95


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def start(conn: sqlite3.Connection, agent_id: str, task: str,
          env_id: str | None = None) -> Session:
    s = Session(agent_id=agent_id, task=task, env_id=env_id)
    database.insert_session(conn, s)
    return s


def set_memories(conn: sqlite3.Connection, session_id: str,
                 used: list[str], created: list[str]) -> Session:
    s = database.get_session(conn, session_id)
    if s is None:
        raise ValueError(f"unknown session {session_id}")
    s.memories_used = used
    s.memories_created = created
    database.update_session(conn, s)
    return s


def complete(conn: sqlite3.Connection, session_id: str,
             outcome: dict[str, Any]) -> tuple[Session, Agent]:
    s = database.get_session(conn, session_id)
    if s is None:
        raise ValueError(f"unknown session {session_id}")
    succeeded = float(outcome.get("accuracy", 0.0)) >= SUCCESS_THRESHOLD
    s.status = "completed" if succeeded else "failed"
    s.outcome = outcome
    s.ended_at = datetime.now(timezone.utc)
    database.update_session(conn, s)

    used = set(s.memories_used)
    delta = 0.1 if succeeded else -0.05
    for m in database.list_memories(conn, s.agent_id):
        if m.id in used:
            m.relevance_score = _clamp(m.relevance_score + delta)
            m.sessions_since_used = 0
        else:
            m.sessions_since_used += 1
            if m.sessions_since_used >= IDLE_DECAY_SESSIONS:
                m.relevance_score = _clamp(m.relevance_score * IDLE_DECAY_FACTOR)
        database.update_memory(conn, m)

    agent = reputation.update_after_session(conn, s.agent_id)
    return s, agent
