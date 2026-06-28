from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from core.models import Agent, Approval, Memory, PolicyRule, Session, SkillVersion

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
  id TEXT PRIMARY KEY, description TEXT, condition TEXT, route_to TEXT,
  action TEXT, version INTEGER
);
CREATE TABLE IF NOT EXISTS crm_records (
  deal_id TEXT PRIMARY KEY, data TEXT
);
CREATE TABLE IF NOT EXISTS approvals (
  id TEXT PRIMARY KEY, request_id TEXT NOT NULL, method TEXT NOT NULL,
  join_mode TEXT NOT NULL, step_id TEXT NOT NULL, depends_on TEXT NOT NULL,
  deal_id TEXT, discrepancy TEXT, approver_role TEXT,
  status TEXT, comment TEXT NOT NULL DEFAULT '', token TEXT, created_at TEXT, decided_at TEXT
);
CREATE TABLE IF NOT EXISTS skill_versions (
  id TEXT PRIMARY KEY, agent_id TEXT NOT NULL, version INTEGER NOT NULL,
  content TEXT NOT NULL, score REAL, parent_version INTEGER, rationale TEXT,
  active INTEGER DEFAULT 0, created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_skill_versions_agent ON skill_versions(agent_id, version);
"""


def get_connection(path: Path | str = DB_PATH) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    _ensure_policy_action_column(conn)
    _ensure_approval_graph_columns(conn)
    conn.commit()


def _ensure_policy_action_column(conn: sqlite3.Connection) -> None:
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(policy_rules)").fetchall()}
    if "action" not in cols:
        conn.execute("ALTER TABLE policy_rules ADD COLUMN action TEXT DEFAULT 'escalate'")


def _ensure_approval_graph_columns(conn: sqlite3.Connection) -> None:
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(approvals)").fetchall()}
    migrations = {
        "request_id": "ALTER TABLE approvals ADD COLUMN request_id TEXT NOT NULL DEFAULT ''",
        "method": "ALTER TABLE approvals ADD COLUMN method TEXT NOT NULL DEFAULT 'approval.route'",
        "join_mode": "ALTER TABLE approvals ADD COLUMN join_mode TEXT NOT NULL DEFAULT 'all'",
        "step_id": "ALTER TABLE approvals ADD COLUMN step_id TEXT NOT NULL DEFAULT ''",
        "depends_on": "ALTER TABLE approvals ADD COLUMN depends_on TEXT NOT NULL DEFAULT '[]'",
        "comment": "ALTER TABLE approvals ADD COLUMN comment TEXT NOT NULL DEFAULT ''",
    }
    for column, statement in migrations.items():
        if column not in cols:
            conn.execute(statement)
    conn.execute("UPDATE approvals SET request_id=id WHERE request_id=''")


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
                 permission_tier=row["permission_tier"], created_at=datetime.fromisoformat(row["created_at"]))


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
                  created_at=datetime.fromisoformat(row["created_at"]), last_used_at=_dt(row["last_used_at"]))


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
                   started_at=datetime.fromisoformat(row["started_at"]), ended_at=_dt(row["ended_at"]))


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
        "INSERT INTO policy_rules (id, description, condition, route_to, action, version) "
        "VALUES (?,?,?,?,?,?) "
        "ON CONFLICT(id) DO UPDATE SET description=excluded.description,"
        "condition=excluded.condition,route_to=excluded.route_to,"
        "action=excluded.action,version=excluded.version",
        (r.id, r.description, json.dumps(r.condition), r.route_to, r.action, r.version),
    )
    conn.commit()


def _policy_from_row(row: sqlite3.Row) -> PolicyRule:
    return PolicyRule(id=row["id"], description=row["description"],
                      condition=json.loads(row["condition"]), route_to=row["route_to"],
                      action=row["action"] or "escalate", version=row["version"])


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


# --- approvals ---
def insert_approval(conn: sqlite3.Connection, a: Approval) -> None:
    conn.execute(
        """
        INSERT INTO approvals (
          id, request_id, method, join_mode, step_id, depends_on, deal_id,
          discrepancy, approver_role, status, comment, token, created_at, decided_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (a.id, a.request_id, a.method, a.join, a.step_id, json.dumps(a.depends_on),
         a.deal_id, json.dumps(a.discrepancy), a.approver_role, a.status,
         a.comment, a.token, a.created_at.isoformat(),
         a.decided_at.isoformat() if a.decided_at else None),
    )
    conn.commit()


def insert_approvals(conn: sqlite3.Connection, approvals: list[Approval]) -> None:
    for approval in approvals:
        insert_approval(conn, approval)


def _approval_from_row(row: sqlite3.Row) -> Approval:
    return Approval(id=row["id"], request_id=row["request_id"], method=row["method"],
                    join=row["join_mode"], step_id=row["step_id"],
                    depends_on=json.loads(row["depends_on"]),
                    deal_id=row["deal_id"], discrepancy=json.loads(row["discrepancy"]),
                    approver_role=row["approver_role"], status=row["status"],
                    comment=row["comment"],
                    token=row["token"], created_at=datetime.fromisoformat(row["created_at"]),
                    decided_at=_dt(row["decided_at"]))


def get_approval(conn: sqlite3.Connection, approval_id: str) -> Approval | None:
    row = conn.execute("SELECT * FROM approvals WHERE id=?", (approval_id,)).fetchone()
    return _approval_from_row(row) if row else None


def list_approvals_for_request(conn: sqlite3.Connection, request_id: str) -> list[Approval]:
    rows = conn.execute(
        "SELECT * FROM approvals WHERE request_id=? ORDER BY created_at, step_id",
        (request_id,),
    ).fetchall()
    return [_approval_from_row(row) for row in rows]


def list_approval_requests(conn: sqlite3.Connection, deal_id: str | None = None) -> list[Approval]:
    """One representative approval (earliest step) per request_id, optionally filtered by deal."""
    if deal_id:
        rows = conn.execute(
            "SELECT * FROM approvals WHERE deal_id=? ORDER BY created_at, step_id", (deal_id,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM approvals ORDER BY created_at, step_id").fetchall()
    by_request: dict[str, Approval] = {}
    for row in rows:
        a = _approval_from_row(row)
        by_request.setdefault(a.request_id, a)
    return list(by_request.values())


def list_pending_approvals_for_role(conn: sqlite3.Connection, role: str) -> list[Approval]:
    rows = conn.execute(
        """
        SELECT * FROM approvals
        WHERE approver_role=? AND status=?
        ORDER BY created_at, step_id
        """,
        (role, "pending"),
    ).fetchall()
    return [_approval_from_row(row) for row in rows]


def update_approval(conn: sqlite3.Connection, a: Approval) -> None:
    conn.execute(
        "UPDATE approvals SET status=?, comment=?, decided_at=? WHERE id=?",
        (a.status, a.comment, a.decided_at.isoformat() if a.decided_at else None, a.id),
    )
    conn.commit()


# --- skill versions ---
def _skill_version_from_row(row: sqlite3.Row) -> SkillVersion:
    return SkillVersion(id=row["id"], agent_id=row["agent_id"], version=row["version"],
                        content=row["content"], score=row["score"],
                        parent_version=row["parent_version"], rationale=row["rationale"],
                        active=bool(row["active"]),
                        created_at=datetime.fromisoformat(row["created_at"]))


def insert_skill_version(conn: sqlite3.Connection, sv: SkillVersion) -> None:
    if sv.active:
        conn.execute("UPDATE skill_versions SET active=0 WHERE agent_id=?", (sv.agent_id,))
    conn.execute(
        "INSERT INTO skill_versions "
        "(id, agent_id, version, content, score, parent_version, rationale, active, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (sv.id, sv.agent_id, sv.version, sv.content, sv.score, sv.parent_version,
         sv.rationale, 1 if sv.active else 0, sv.created_at.isoformat()),
    )
    conn.commit()


def get_active_skill(conn: sqlite3.Connection, agent_id: str) -> SkillVersion | None:
    row = conn.execute(
        "SELECT * FROM skill_versions WHERE agent_id=? AND active=1 ORDER BY version DESC LIMIT 1",
        (agent_id,),
    ).fetchone()
    return _skill_version_from_row(row) if row else None


def list_skill_versions(conn: sqlite3.Connection, agent_id: str) -> list[SkillVersion]:
    rows = conn.execute(
        "SELECT * FROM skill_versions WHERE agent_id=? ORDER BY version", (agent_id,)
    ).fetchall()
    return [_skill_version_from_row(r) for r in rows]


def set_active_skill(conn: sqlite3.Connection, agent_id: str, version: int) -> None:
    conn.execute("UPDATE skill_versions SET active=0 WHERE agent_id=?", (agent_id,))
    conn.execute("UPDATE skill_versions SET active=1 WHERE agent_id=? AND version=?",
                 (agent_id, version))
    conn.commit()


def next_skill_version(conn: sqlite3.Connection, agent_id: str) -> int:
    row = conn.execute(
        "SELECT MAX(version) AS m FROM skill_versions WHERE agent_id=?", (agent_id,)
    ).fetchone()
    return 0 if row is None or row["m"] is None else int(row["m"]) + 1
