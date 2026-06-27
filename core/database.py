from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from core.models import Agent, Memory, PolicyRule, Session

DB_PATH = Path("db/revmem.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS agents (
  id TEXT PRIMARY KEY, name TEXT, reputation_score REAL,
  total_sessions INTEGER, successful_sessions INTEGER,
  permission_tier TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS memories (
  id TEXT PRIMARY KEY, session_id TEXT, agent_id TEXT, type TEXT, content TEXT,
  embedding TEXT, metadata TEXT, relevance_score REAL, access_count INTEGER,
  sessions_since_used INTEGER, created_at TEXT, last_used_at TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY, agent_id TEXT, env_id TEXT, task TEXT, status TEXT,
  outcome TEXT, memories_used TEXT, memories_created TEXT,
  started_at TEXT, ended_at TEXT
);
CREATE TABLE IF NOT EXISTS policy_rules (
  id TEXT PRIMARY KEY, description TEXT, condition TEXT, route_to TEXT, version INTEGER
);
CREATE TABLE IF NOT EXISTS crm_records (
  deal_id TEXT PRIMARY KEY, data TEXT
);
"""


def get_connection(path: Path | str = DB_PATH) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


# --- agents ---
def insert_agent(conn: sqlite3.Connection, a: Agent) -> None:
    conn.execute(
        "INSERT INTO agents VALUES (?,?,?,?,?,?,?)",
        (a.id, a.name, a.reputation_score, a.total_sessions,
         a.successful_sessions, a.permission_tier, a.created_at.isoformat()),
    )
    conn.commit()


def get_agent(conn: sqlite3.Connection, agent_id: str) -> Agent | None:
    row = conn.execute("SELECT * FROM agents WHERE id=?", (agent_id,)).fetchone()
    if not row:
        return None
    return Agent(id=row["id"], name=row["name"], reputation_score=row["reputation_score"],
                 total_sessions=row["total_sessions"], successful_sessions=row["successful_sessions"],
                 permission_tier=row["permission_tier"], created_at=_dt(row["created_at"]))


def get_agent_by_name(conn: sqlite3.Connection, name: str) -> Agent | None:
    row = conn.execute("SELECT id FROM agents WHERE name=? LIMIT 1", (name,)).fetchone()
    return get_agent(conn, row["id"]) if row else None


def update_agent(conn: sqlite3.Connection, a: Agent) -> None:
    conn.execute(
        "UPDATE agents SET name=?,reputation_score=?,total_sessions=?,"
        "successful_sessions=?,permission_tier=? WHERE id=?",
        (a.name, a.reputation_score, a.total_sessions, a.successful_sessions,
         a.permission_tier, a.id),
    )
    conn.commit()


# --- memories ---
def insert_memory(conn: sqlite3.Connection, m: Memory) -> None:
    conn.execute(
        "INSERT INTO memories VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (m.id, m.session_id, m.agent_id, m.type, m.content,
         json.dumps(m.embedding), json.dumps(m.metadata), m.relevance_score,
         m.access_count, m.sessions_since_used, m.created_at.isoformat(),
         m.last_used_at.isoformat() if m.last_used_at else None),
    )
    conn.commit()


def _memory_from_row(row: sqlite3.Row) -> Memory:
    return Memory(id=row["id"], session_id=row["session_id"], agent_id=row["agent_id"],
                  type=row["type"], content=row["content"],
                  embedding=json.loads(row["embedding"]), metadata=json.loads(row["metadata"]),
                  relevance_score=row["relevance_score"], access_count=row["access_count"],
                  sessions_since_used=row["sessions_since_used"],
                  created_at=_dt(row["created_at"]), last_used_at=_dt(row["last_used_at"]))


def get_memory(conn: sqlite3.Connection, memory_id: str) -> Memory | None:
    row = conn.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
    return _memory_from_row(row) if row else None


def list_memories(conn: sqlite3.Connection, agent_id: str, type: str | None = None) -> list[Memory]:
    if type is not None:
        rows = conn.execute("SELECT * FROM memories WHERE agent_id=? AND type=?",
                            (agent_id, type)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM memories WHERE agent_id=?", (agent_id,)).fetchall()
    return [_memory_from_row(r) for r in rows]


def update_memory(conn: sqlite3.Connection, m: Memory) -> None:
    conn.execute(
        "UPDATE memories SET content=?,embedding=?,metadata=?,relevance_score=?,"
        "access_count=?,sessions_since_used=?,last_used_at=? WHERE id=?",
        (m.content, json.dumps(m.embedding), json.dumps(m.metadata), m.relevance_score,
         m.access_count, m.sessions_since_used,
         m.last_used_at.isoformat() if m.last_used_at else None, m.id),
    )
    conn.commit()


# --- sessions ---
def insert_session(conn: sqlite3.Connection, s: Session) -> None:
    conn.execute(
        "INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?)",
        (s.id, s.agent_id, s.env_id, s.task, s.status,
         json.dumps(s.outcome) if s.outcome else None,
         json.dumps(s.memories_used), json.dumps(s.memories_created),
         s.started_at.isoformat(), s.ended_at.isoformat() if s.ended_at else None),
    )
    conn.commit()


def _session_from_row(row: sqlite3.Row) -> Session:
    return Session(id=row["id"], agent_id=row["agent_id"], env_id=row["env_id"],
                   task=row["task"], status=row["status"],
                   outcome=json.loads(row["outcome"]) if row["outcome"] else None,
                   memories_used=json.loads(row["memories_used"]),
                   memories_created=json.loads(row["memories_created"]),
                   started_at=_dt(row["started_at"]), ended_at=_dt(row["ended_at"]))


def get_session(conn: sqlite3.Connection, session_id: str) -> Session | None:
    row = conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
    return _session_from_row(row) if row else None


def update_session(conn: sqlite3.Connection, s: Session) -> None:
    conn.execute(
        "UPDATE sessions SET status=?,outcome=?,memories_used=?,memories_created=?,"
        "ended_at=? WHERE id=?",
        (s.status, json.dumps(s.outcome) if s.outcome else None,
         json.dumps(s.memories_used), json.dumps(s.memories_created),
         s.ended_at.isoformat() if s.ended_at else None, s.id),
    )
    conn.commit()


def list_sessions(conn: sqlite3.Connection, agent_id: str | None = None) -> list[Session]:
    if agent_id:
        rows = conn.execute("SELECT * FROM sessions WHERE agent_id=? ORDER BY started_at",
                            (agent_id,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM sessions ORDER BY started_at").fetchall()
    return [_session_from_row(r) for r in rows]


# --- policy ---
def upsert_policy(conn: sqlite3.Connection, r: PolicyRule) -> None:
    conn.execute(
        "INSERT INTO policy_rules VALUES (?,?,?,?,?) "
        "ON CONFLICT(id) DO UPDATE SET description=excluded.description,"
        "condition=excluded.condition,route_to=excluded.route_to,version=excluded.version",
        (r.id, r.description, json.dumps(r.condition), r.route_to, r.version),
    )
    conn.commit()


def _policy_from_row(row: sqlite3.Row) -> PolicyRule:
    return PolicyRule(id=row["id"], description=row["description"],
                      condition=json.loads(row["condition"]), route_to=row["route_to"],
                      version=row["version"])


def get_policy(conn: sqlite3.Connection, policy_id: str) -> PolicyRule | None:
    row = conn.execute("SELECT * FROM policy_rules WHERE id=?", (policy_id,)).fetchone()
    return _policy_from_row(row) if row else None


def list_policy(conn: sqlite3.Connection) -> list[PolicyRule]:
    rows = conn.execute("SELECT * FROM policy_rules").fetchall()
    return [_policy_from_row(r) for r in rows]


# --- crm ---
def upsert_crm(conn: sqlite3.Connection, deal_id: str, data: dict[str, Any]) -> None:
    conn.execute(
        "INSERT INTO crm_records VALUES (?,?) "
        "ON CONFLICT(deal_id) DO UPDATE SET data=excluded.data",
        (deal_id, json.dumps(data)),
    )
    conn.commit()


def get_crm(conn: sqlite3.Connection, deal_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT data FROM crm_records WHERE deal_id=?", (deal_id,)).fetchone()
    return json.loads(row["data"]) if row else None
