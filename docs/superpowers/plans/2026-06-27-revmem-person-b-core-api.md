# RevMem Person B — Core Engine + API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build RevMem's core engine (memory, governance, reputation), a FastAPI tool server, and mock finance data on SQLite, exposed to the hosted Gemini agent via ngrok.

**Architecture:** A Python package with a thin SQLite repository layer (`core/database.py`), pure-Python domain engines (`core/context.py` retrieval+rerank, `core/reputation.py` scoring, `core/governance.py` routing+tier gating, `core/session.py` lifecycle), and a FastAPI app (`api/`) exposing the exact tools the Antigravity agent calls plus the reads the React UI needs. Mock contracts are static JSON; mutable CRM records, policy, agents, sessions and memories live in SQLite.

**Tech Stack:** Python 3.11, FastAPI, uvicorn, Pydantic v2, sqlite3 (stdlib), google-genai (embeddings, with deterministic offline fallback), pytest, httpx (FastAPI TestClient).

## Global Constraints

- Python 3.11+. Run everything with `uv` (`uv run ...`, `uv add ...`).
- Fully type-hinted. No bare `any`. Pydantic v2 models.
- SQLite file at `db/revmem.db` (add `db/` to `.gitignore`). Open with `check_same_thread=False`.
- All timestamps are timezone-aware UTC, stored as ISO-8601 strings.
- Embeddings via `google-genai`; if `GEMINI_API_KEY` is unset or the call fails, fall back to a deterministic local hash embedding so tests run offline.
- Retrieval rerank formula (exact): `score = 0.5*cosine + 0.4*relevance_score + 0.1*recency`.
- Permission tiers (exact thresholds): `reputation < 0.3 → observer`, `< 0.6 → analyst`, `>= 0.6 → autonomous`.
- Agent tool names must match `ARCHITECTURE.md` exactly: `get_contract`, `get_crm_record`, `retrieve_context`, `route_for_approval`, `write_crm`, `log_outcome`, `store_memory`.
- RevMem base URL is read from env (`REVMEM_BASE_URL`) by consumers; never hardcode the ngrok URL.

## File Structure

| File | Responsibility |
|------|----------------|
| `core/models.py` | Pydantic models + tier/type constants |
| `core/database.py` | SQLite connection, schema, row CRUD |
| `core/context.py` | Embeddings, cosine, retrieve + rerank, relevance updates |
| `core/reputation.py` | Score computation, tier mapping, post-session update |
| `core/governance.py` | Policy routing, tier→tools gating, SKILL.md generation |
| `core/session.py` | Session lifecycle, outcome → triggers reputation + relevance |
| `api/main.py` | FastAPI app, CORS, lifespan (init_db + seed) |
| `api/routes.py` | REST endpoints = agent tools + UI reads + live policy edit |
| `data/contracts.json` | Acme + Globex signed order forms (read-only) |
| `data/salesforce.json` | Stale CRM records (seeded into mutable table) |
| `data/policy.json` | DOA policy rules |
| `data/seed.py` | Load mock data + create demo agent |
| `tests/conftest.py` | Temp-DB fixture |
| `tests/test_*.py` | One test module per core module + api smoke |

**Out of scope (other people):** `agent/` (Person A) and `ui/` (Person C). This plan's `Interfaces → Produces` blocks are the contract they consume.

---

### Task 1: Project scaffold + data models

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `core/__init__.py`, `core/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Produces: `Memory`, `PolicyRule`, `Session`, `Agent` Pydantic models; constant classes `PermissionTier{OBSERVER,ANALYST,AUTONOMOUS}` and `MemoryType{PRICING_FIELD_RULE,MATERIALITY_THRESHOLD,CONTRACT_TERM,CRM_RECORD}`.

- [ ] **Step 1: Initialize project and dependencies**

```bash
cd revmem
uv init --no-readme
uv add fastapi "uvicorn[standard]" "pydantic>=2" google-genai
uv add --dev pytest httpx
printf "db/\n__pycache__/\n.venv/\n*.pyc\n" > .gitignore
mkdir -p core api data tests
touch core/__init__.py api/__init__.py
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_models.py
from core.models import Memory, Agent, PermissionTier, MemoryType


def test_memory_defaults():
    m = Memory(session_id="s1", agent_id="a1",
               type=MemoryType.PRICING_FIELD_RULE, content="check the schedule")
    assert m.relevance_score == 0.5
    assert m.access_count == 0
    assert m.last_used_at is None
    assert isinstance(m.id, str) and len(m.id) > 0
    assert m.embedding == []


def test_agent_defaults():
    a = Agent(name="RevOps Agent")
    assert a.reputation_score == 0.1
    assert a.permission_tier == PermissionTier.OBSERVER
    assert a.total_sessions == 0
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.models'`

- [ ] **Step 4: Write minimal implementation**

```python
# core/models.py
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, Field


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class PermissionTier:
    OBSERVER = "observer"
    ANALYST = "analyst"
    AUTONOMOUS = "autonomous"


class MemoryType:
    PRICING_FIELD_RULE = "pricing_field_rule"
    MATERIALITY_THRESHOLD = "materiality_threshold"
    CONTRACT_TERM = "contract_term"
    CRM_RECORD = "crm_record"


class Memory(BaseModel):
    id: str = Field(default_factory=_uuid)
    session_id: str
    agent_id: str
    type: str
    content: str
    embedding: list[float] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)
    relevance_score: float = 0.5
    access_count: int = 0
    created_at: datetime = Field(default_factory=_now)
    last_used_at: datetime | None = None


class PolicyRule(BaseModel):
    id: str = Field(default_factory=_uuid)
    description: str
    condition: dict
    route_to: str
    version: int = 1


class Session(BaseModel):
    id: str = Field(default_factory=_uuid)
    agent_id: str
    env_id: str | None = None
    task: str
    status: str = "running"
    outcome: dict | None = None
    memories_used: list[str] = Field(default_factory=list)
    memories_created: list[str] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=_now)
    ended_at: datetime | None = None


class Agent(BaseModel):
    id: str = Field(default_factory=_uuid)
    name: str
    reputation_score: float = 0.1
    total_sessions: int = 0
    successful_sessions: int = 0
    permission_tier: str = PermissionTier.OBSERVER
    created_at: datetime = Field(default_factory=_now)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_models.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml .gitignore core/ tests/test_models.py
git commit -m "feat: scaffold project and core data models"
```

---

### Task 2: SQLite repository layer

**Files:**
- Create: `core/database.py`
- Test: `tests/conftest.py`, `tests/test_database.py`

**Interfaces:**
- Consumes: models from Task 1.
- Produces:
  - `get_connection(path) -> sqlite3.Connection`
  - `init_db(conn) -> None`
  - `insert_agent(conn, Agent) -> None`, `get_agent(conn, id) -> Agent | None`, `update_agent(conn, Agent) -> None`
  - `insert_memory(conn, Memory) -> None`, `get_memory(conn, id) -> Memory | None`, `list_memories(conn, agent_id, type=None) -> list[Memory]`, `update_memory(conn, Memory) -> None`
  - `insert_session(conn, Session) -> None`, `get_session(conn, id) -> Session | None`, `update_session(conn, Session) -> None`, `list_sessions(conn, agent_id=None) -> list[Session]`
  - `upsert_policy(conn, PolicyRule) -> None`, `list_policy(conn) -> list[PolicyRule]`, `get_policy(conn, id) -> PolicyRule | None`
  - `upsert_crm(conn, deal_id, data: dict) -> None`, `get_crm(conn, deal_id) -> dict | None`

- [ ] **Step 1: Write the shared DB fixture**

```python
# tests/conftest.py
import pytest

from core import database


@pytest.fixture()
def conn(tmp_path):
    c = database.get_connection(tmp_path / "test.db")
    database.init_db(c)
    yield c
    c.close()
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_database.py
from core import database
from core.models import Agent, Memory, MemoryType, PolicyRule


def test_agent_roundtrip(conn):
    a = Agent(name="A")
    database.insert_agent(conn, a)
    got = database.get_agent(conn, a.id)
    assert got is not None and got.name == "A" and got.reputation_score == 0.1


def test_memory_list_filter(conn):
    a = Agent(name="A")
    database.insert_agent(conn, a)
    m1 = Memory(session_id="s", agent_id=a.id, type=MemoryType.PRICING_FIELD_RULE,
                content="schedule", embedding=[0.1, 0.2])
    m2 = Memory(session_id="s", agent_id=a.id, type=MemoryType.CONTRACT_TERM, content="term")
    database.insert_memory(conn, m1)
    database.insert_memory(conn, m2)
    only = database.list_memories(conn, a.id, MemoryType.PRICING_FIELD_RULE)
    assert len(only) == 1 and only[0].embedding == [0.1, 0.2]


def test_crm_mutable(conn):
    database.upsert_crm(conn, "acme", {"tcv": 450000})
    database.upsert_crm(conn, "acme", {"tcv": 450000, "schedule": [100, 150, 200]})
    assert database.get_crm(conn, "acme") == {"tcv": 450000, "schedule": [100, 150, 200]}


def test_policy_roundtrip(conn):
    r = PolicyRule(description="rounding", condition={"max_usd": 1000}, route_to="am")
    database.upsert_policy(conn, r)
    rules = database.list_policy(conn)
    assert len(rules) == 1 and rules[0].route_to == "am"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_database.py -v`
Expected: FAIL with `AttributeError: module 'core.database' has no attribute 'get_connection'`

- [ ] **Step 4: Write minimal implementation**

```python
# core/database.py
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

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
  created_at TEXT, last_used_at TEXT
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
        "INSERT INTO memories VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (m.id, m.session_id, m.agent_id, m.type, m.content,
         json.dumps(m.embedding), json.dumps(m.metadata), m.relevance_score,
         m.access_count, m.created_at.isoformat(),
         m.last_used_at.isoformat() if m.last_used_at else None),
    )
    conn.commit()


def _memory_from_row(row: sqlite3.Row) -> Memory:
    return Memory(id=row["id"], session_id=row["session_id"], agent_id=row["agent_id"],
                  type=row["type"], content=row["content"],
                  embedding=json.loads(row["embedding"]), metadata=json.loads(row["metadata"]),
                  relevance_score=row["relevance_score"], access_count=row["access_count"],
                  created_at=_dt(row["created_at"]), last_used_at=_dt(row["last_used_at"]))


def get_memory(conn: sqlite3.Connection, memory_id: str) -> Memory | None:
    row = conn.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
    return _memory_from_row(row) if row else None


def list_memories(conn: sqlite3.Connection, agent_id: str, type: str | None = None) -> list[Memory]:
    if type:
        rows = conn.execute("SELECT * FROM memories WHERE agent_id=? AND type=?",
                            (agent_id, type)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM memories WHERE agent_id=?", (agent_id,)).fetchall()
    return [_memory_from_row(r) for r in rows]


def update_memory(conn: sqlite3.Connection, m: Memory) -> None:
    conn.execute(
        "UPDATE memories SET content=?,embedding=?,metadata=?,relevance_score=?,"
        "access_count=?,last_used_at=? WHERE id=?",
        (m.content, json.dumps(m.embedding), json.dumps(m.metadata), m.relevance_score,
         m.access_count, m.last_used_at.isoformat() if m.last_used_at else None, m.id),
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
def upsert_crm(conn: sqlite3.Connection, deal_id: str, data: dict) -> None:
    conn.execute(
        "INSERT INTO crm_records VALUES (?,?) "
        "ON CONFLICT(deal_id) DO UPDATE SET data=excluded.data",
        (deal_id, json.dumps(data)),
    )
    conn.commit()


def get_crm(conn: sqlite3.Connection, deal_id: str) -> dict | None:
    row = conn.execute("SELECT data FROM crm_records WHERE deal_id=?", (deal_id,)).fetchone()
    return json.loads(row["data"]) if row else None
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_database.py -v`
Expected: PASS (4 passed)

- [ ] **Step 6: Commit**

```bash
git add core/database.py tests/conftest.py tests/test_database.py
git commit -m "feat: SQLite repository layer"
```

---

### Task 3: Reputation engine

**Files:**
- Create: `core/reputation.py`
- Test: `tests/test_reputation.py`

**Interfaces:**
- Consumes: `database`, `Agent`, `PermissionTier`.
- Produces:
  - `tier_for(score: float) -> str`
  - `compute(success_rate: float, avg_accuracy: float) -> float`  (`0.6*success_rate + 0.4*avg_accuracy`, clamped)
  - `update_after_session(conn, agent_id: str) -> Agent`  (recomputes from all completed sessions; persists; returns agent)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_reputation.py
from core import database, reputation, session
from core.models import Agent, PermissionTier


def _run(conn, agent_id, accuracy):
    s = session.start(conn, agent_id, task="reconcile")
    session.complete(conn, s.id, {"accuracy": accuracy})


def test_tier_boundaries():
    assert reputation.tier_for(0.0) == PermissionTier.OBSERVER
    assert reputation.tier_for(0.29) == PermissionTier.OBSERVER
    assert reputation.tier_for(0.3) == PermissionTier.ANALYST
    assert reputation.tier_for(0.59) == PermissionTier.ANALYST
    assert reputation.tier_for(0.6) == PermissionTier.AUTONOMOUS


def test_demo_trajectory(conn):
    a = Agent(name="A")
    database.insert_agent(conn, a)
    _run(conn, a.id, 0.0)   # S1 cold: miss
    assert database.get_agent(conn, a.id).permission_tier == PermissionTier.OBSERVER
    _run(conn, a.id, 1.0)   # S2: correct
    assert database.get_agent(conn, a.id).permission_tier == PermissionTier.ANALYST
    _run(conn, a.id, 1.0)   # S3: correct
    assert database.get_agent(conn, a.id).permission_tier == PermissionTier.AUTONOMOUS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_reputation.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'core.reputation'`, and `core.session` not yet present)

- [ ] **Step 3: Write minimal implementation**

```python
# core/reputation.py
from __future__ import annotations

import sqlite3

from core import database
from core.models import Agent, PermissionTier

SUCCESS_THRESHOLD = 0.5


def tier_for(score: float) -> str:
    if score < 0.3:
        return PermissionTier.OBSERVER
    if score < 0.6:
        return PermissionTier.ANALYST
    return PermissionTier.AUTONOMOUS


def compute(success_rate: float, avg_accuracy: float) -> float:
    return max(0.0, min(1.0, 0.6 * success_rate + 0.4 * avg_accuracy))


def update_after_session(conn: sqlite3.Connection, agent_id: str) -> Agent:
    agent = database.get_agent(conn, agent_id)
    if agent is None:
        raise ValueError(f"unknown agent {agent_id}")
    completed = [s for s in database.list_sessions(conn, agent_id)
                 if s.status in ("completed", "failed") and s.outcome is not None]
    accuracies = [float(s.outcome.get("accuracy", 0.0)) for s in completed]
    total = len(completed)
    successful = sum(1 for x in accuracies if x >= SUCCESS_THRESHOLD)
    avg_accuracy = sum(accuracies) / total if total else 0.0
    success_rate = successful / total if total else 0.0

    agent.total_sessions = total
    agent.successful_sessions = successful
    agent.reputation_score = compute(success_rate, avg_accuracy)
    agent.permission_tier = tier_for(agent.reputation_score)
    database.update_agent(conn, agent)
    return agent
```

- [ ] **Step 4: Run after Task 4 (depends on `core.session`)**

This test imports `core.session`; it goes green once Task 4 lands. For now run only the boundary test:
Run: `uv run pytest tests/test_reputation.py::test_tier_boundaries -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/reputation.py tests/test_reputation.py
git commit -m "feat: reputation scoring and tier mapping"
```

---

### Task 4: Session lifecycle

**Files:**
- Create: `core/session.py`
- Test: `tests/test_session.py`

**Interfaces:**
- Consumes: `database`, `reputation`, `Session`, `Memory`.
- Produces:
  - `start(conn, agent_id, task, env_id=None) -> Session`
  - `set_memories(conn, session_id, used: list[str], created: list[str]) -> Session`
  - `complete(conn, session_id, outcome: dict) -> tuple[Session, Agent]`  (sets status from `outcome["accuracy"]`, applies relevance update to `memories_used`, triggers `reputation.update_after_session`)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_session.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_session.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'core.session'`)

- [ ] **Step 3: Write minimal implementation**

```python
# core/session.py
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from core import database, reputation
from core.models import Agent, Session

SUCCESS_THRESHOLD = 0.5


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
             outcome: dict) -> tuple[Session, Agent]:
    s = database.get_session(conn, session_id)
    if s is None:
        raise ValueError(f"unknown session {session_id}")
    succeeded = float(outcome.get("accuracy", 0.0)) >= SUCCESS_THRESHOLD
    s.status = "completed" if succeeded else "failed"
    s.outcome = outcome
    s.ended_at = datetime.now(timezone.utc)
    database.update_session(conn, s)

    delta = 0.1 if succeeded else -0.05
    for mid in s.memories_used:
        m = database.get_memory(conn, mid)
        if m is None:
            continue
        m.relevance_score = _clamp(m.relevance_score + delta)
        database.update_memory(conn, m)

    agent = reputation.update_after_session(conn, s.agent_id)
    return s, agent
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_session.py tests/test_reputation.py -v`
Expected: PASS (all, including `test_demo_trajectory`)

- [ ] **Step 5: Commit**

```bash
git add core/session.py tests/test_session.py
git commit -m "feat: session lifecycle with relevance + reputation triggers"
```

---

### Task 5: Context engine (embeddings + retrieve/rerank)

**Files:**
- Create: `core/context.py`
- Test: `tests/test_context.py`

**Interfaces:**
- Consumes: `database`, `Memory`.
- Produces:
  - `embed_text(text: str) -> list[float]`  (Gemini if key present, else deterministic hash)
  - `cosine(a: list[float], b: list[float]) -> float`
  - `score_memory(m: Memory, query_emb: list[float], now: datetime) -> float`
  - `retrieve(conn, agent_id, query, memory_type=None, limit=5, now=None) -> list[Memory]`  (ranks by the formula, bumps `access_count`/`last_used_at` on returned rows)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_context.py
from datetime import datetime, timezone

from core import context, database
from core.models import Agent, Memory, MemoryType


def test_cosine_basic():
    assert context.cosine([1, 0], [1, 0]) == 1.0
    assert context.cosine([1, 0], [0, 1]) == 0.0
    assert context.cosine([], [1, 0]) == 0.0


def test_retrieve_orders_by_relevance(conn, monkeypatch):
    # deterministic embeddings: identical vector so cosine term is constant
    monkeypatch.setattr(context, "embed_text", lambda t: [1.0, 0.0])
    a = Agent(name="A")
    database.insert_agent(conn, a)
    low = Memory(session_id="s", agent_id=a.id, type=MemoryType.PRICING_FIELD_RULE,
                 content="low", embedding=[1.0, 0.0], relevance_score=0.2)
    high = Memory(session_id="s", agent_id=a.id, type=MemoryType.PRICING_FIELD_RULE,
                  content="high", embedding=[1.0, 0.0], relevance_score=0.9)
    database.insert_memory(conn, low)
    database.insert_memory(conn, high)
    out = context.retrieve(conn, a.id, query="anything", limit=2)
    assert [m.content for m in out] == ["high", "low"]
    assert database.get_memory(conn, high.id).access_count == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_context.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'core.context'`)

- [ ] **Step 3: Write minimal implementation**

```python
# core/context.py
from __future__ import annotations

import hashlib
import math
import os
import sqlite3
from datetime import datetime, timezone

from core import database
from core.models import Memory

EMBED_DIM = 256
ALPHA, BETA, GAMMA = 0.5, 0.4, 0.1


def embed_text(text: str) -> list[float]:
    key = os.getenv("GEMINI_API_KEY")
    if key:
        try:
            # Signature verified against google-genai (googleapis/python-genai):
            # client.models.embed_content(model, contents, config) ->
            #   response.embeddings[i].values: list[float]
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=key)
            result = client.models.embed_content(
                model="gemini-embedding-001",
                contents=text,
                config=types.EmbedContentConfig(output_dimensionality=EMBED_DIM),
            )
            return list(result.embeddings[0].values)
        except Exception:
            pass
    return _hash_embed(text)


def _hash_embed(text: str) -> list[float]:
    vec = [0.0] * EMBED_DIM
    for token in text.lower().split():
        idx = int(hashlib.md5(token.encode()).hexdigest(), 16) % EMBED_DIM
        vec[idx] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _recency(created_at: datetime, now: datetime) -> float:
    age_days = max((now - created_at).total_seconds() / 86400.0, 0.0)
    return 1.0 / (1.0 + age_days)


def score_memory(m: Memory, query_emb: list[float], now: datetime) -> float:
    return (ALPHA * cosine(query_emb, m.embedding)
            + BETA * m.relevance_score
            + GAMMA * _recency(m.created_at, now))


def retrieve(conn: sqlite3.Connection, agent_id: str, query: str,
             memory_type: str | None = None, limit: int = 5,
             now: datetime | None = None) -> list[Memory]:
    now = now or datetime.now(timezone.utc)
    memories = database.list_memories(conn, agent_id, memory_type)
    query_emb = embed_text(query)
    ranked = sorted(memories, key=lambda m: score_memory(m, query_emb, now), reverse=True)
    top = ranked[:limit]
    for m in top:
        m.access_count += 1
        m.last_used_at = now
        database.update_memory(conn, m)
    return top
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_context.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add core/context.py tests/test_context.py
git commit -m "feat: context engine with embedding rerank"
```

---

### Task 6: Governance engine

**Files:**
- Create: `core/governance.py`
- Test: `tests/test_governance.py`

**Interfaces:**
- Consumes: `PolicyRule`, `PermissionTier`.
- Produces:
  - `route(discrepancy: dict, rules: list[PolicyRule]) -> str`  (`discrepancy = {amount_usd, change_type}`; change-type overrides win, else amount band; default `"cfo"`)
  - `allowed_tools(tier: str) -> set[str]`
  - `can_use(tier: str, tool: str) -> bool`
  - `generate_skill_md(tier: str) -> str`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_governance.py
from core import governance
from core.models import PermissionTier, PolicyRule

RULES = [
    PolicyRule(description="rounding", condition={"min_usd": 0, "max_usd": 1000}, route_to="am"),
    PolicyRule(description="mid", condition={"min_usd": 1000, "max_usd": 50000}, route_to="controller"),
    PolicyRule(description="schedule", condition={"change_types": ["schedule_change"]}, route_to="cfo"),
    PolicyRule(description="discount", condition={"change_types": ["discount_over_authority"]}, route_to="cfo"),
]


def test_amount_band_routing():
    assert governance.route({"amount_usd": 12, "change_type": "amount_diff"}, RULES) == "am"
    assert governance.route({"amount_usd": 8000, "change_type": "amount_diff"}, RULES) == "controller"


def test_change_type_override_wins():
    # ramp restructuring keeps TCV identical (amount_usd 0) but is material → CFO
    assert governance.route({"amount_usd": 0, "change_type": "schedule_change"}, RULES) == "cfo"
    assert governance.route({"amount_usd": 5, "change_type": "discount_over_authority"}, RULES) == "cfo"


def test_tool_gating():
    assert not governance.can_use(PermissionTier.OBSERVER, "write_crm")
    assert governance.can_use(PermissionTier.ANALYST, "write_crm")
    assert governance.can_use(PermissionTier.OBSERVER, "retrieve_context")


def test_skill_md_grows_with_tier():
    obs = governance.generate_skill_md(PermissionTier.OBSERVER)
    auto = governance.generate_skill_md(PermissionTier.AUTONOMOUS)
    assert "write_crm" not in obs and "write_crm" in auto
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_governance.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'core.governance'`)

- [ ] **Step 3: Write minimal implementation**

```python
# core/governance.py
from __future__ import annotations

from core.models import PermissionTier, PolicyRule

_BASE_TOOLS = {"get_contract", "get_crm_record", "retrieve_context",
               "route_for_approval", "log_outcome"}
TOOLS_BY_TIER: dict[str, set[str]] = {
    PermissionTier.OBSERVER: set(_BASE_TOOLS),
    PermissionTier.ANALYST: _BASE_TOOLS | {"write_crm", "store_memory"},
    PermissionTier.AUTONOMOUS: _BASE_TOOLS | {"write_crm", "store_memory"},
}


def route(discrepancy: dict, rules: list[PolicyRule]) -> str:
    change_type = discrepancy.get("change_type")
    amount = abs(float(discrepancy.get("amount_usd", 0)))
    # 1) change-type overrides (material structural changes ignore amount)
    for r in rules:
        if change_type and change_type in r.condition.get("change_types", []):
            return r.route_to
    # 2) amount bands (rules without change_types)
    for r in rules:
        cond = r.condition
        if cond.get("change_types"):
            continue
        lo = float(cond.get("min_usd", 0))
        hi = cond.get("max_usd")
        if amount >= lo and (hi is None or amount < float(hi)):
            return r.route_to
    return "cfo"


def allowed_tools(tier: str) -> set[str]:
    return TOOLS_BY_TIER[tier]


def can_use(tier: str, tool: str) -> bool:
    return tool in TOOLS_BY_TIER[tier]


def generate_skill_md(tier: str) -> str:
    tools = sorted(allowed_tools(tier))
    lines = [f"# RevOps Finance Agent — Skills ({tier})", "",
             "You reconcile signed contracts against the CRM. Available skills:", ""]
    lines += [f"- `{t}`" for t in tools]
    if tier == PermissionTier.OBSERVER:
        lines += ["", "You are OBSERVER: read and flag only. You may NOT write to the "
                  "CRM — route every discrepancy for approval."]
    elif tier == PermissionTier.ANALYST:
        lines += ["", "You are ANALYST: silently dismiss immaterial diffs; escalate "
                  "material ones; on approval you may `write_crm`."]
    else:
        lines += ["", "You are AUTONOMOUS: reconcile policy-covered fixes directly; "
                  "escalate only genuine judgment calls."]
    return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_governance.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add core/governance.py tests/test_governance.py
git commit -m "feat: governance routing, tier gating, SKILL.md generation"
```

---

### Task 7: Mock data + seed

**Files:**
- Create: `data/contracts.json`, `data/salesforce.json`, `data/policy.json`, `data/seed.py`, `data/__init__.py`
- Test: `tests/test_seed.py`

**Interfaces:**
- Consumes: `database`, `PolicyRule`, `Agent`.
- Produces:
  - `seed(conn, demo_agent_name="RevOps Finance Agent") -> Agent`  (loads policy + CRM, creates the demo agent if none; idempotent)
  - `load_contract(deal_id) -> dict | None`  (reads `data/contracts.json`)
  - `DATA_DIR: Path`

- [ ] **Step 1: Create the mock data files**

```json
// data/contracts.json
{
  "acme": {
    "deal_id": "acme",
    "customer": "Acme Corp",
    "product": "Enterprise Platform",
    "seats": 1000,
    "term_months": 36,
    "tcv": 450000,
    "annual_schedule": [100000, 150000, 200000],
    "discount_pct": 10,
    "y1_monthly_invoice": 8333.33
  },
  "globex": {
    "deal_id": "globex",
    "customer": "Globex Inc",
    "product": "Enterprise Platform",
    "seats": 800,
    "term_months": 36,
    "tcv": 360000,
    "annual_schedule": [80000, 120000, 160000],
    "discount_pct": 25,
    "y1_monthly_invoice": 6666.67
  }
}
```

```json
// data/salesforce.json
{
  "acme": {
    "deal_id": "acme",
    "seats": 1000,
    "tcv": 450000,
    "annual_schedule": [150000, 150000, 150000],
    "discount_pct": 10,
    "y1_monthly_invoice": 8333.00
  },
  "globex": {
    "deal_id": "globex",
    "seats": 800,
    "tcv": 360000,
    "annual_schedule": [120000, 120000, 120000],
    "discount_pct": 20,
    "y1_monthly_invoice": 6666.00
  }
}
```

```json
// data/policy.json
[
  {"description": "Immaterial line diffs < $1k → Account Manager",
   "condition": {"min_usd": 0, "max_usd": 1000}, "route_to": "am"},
  {"description": "$1k–$50k diffs → Controller",
   "condition": {"min_usd": 1000, "max_usd": 50000}, "route_to": "controller"},
  {"description": "Diffs >= $50k → CFO",
   "condition": {"min_usd": 50000, "max_usd": null}, "route_to": "cfo"},
  {"description": "Payment-schedule / ramp changes → CFO",
   "condition": {"change_types": ["schedule_change"]}, "route_to": "cfo"},
  {"description": "Discount beyond deal-desk authority → CFO",
   "condition": {"change_types": ["discount_over_authority"]}, "route_to": "cfo"}
]
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_seed.py
from data import seed
from core import database


def test_seed_is_idempotent(conn):
    a1 = seed.seed(conn)
    a2 = seed.seed(conn)
    assert a1.id == a2.id  # does not create a second agent
    assert len(database.list_policy(conn)) == 5
    assert database.get_crm(conn, "acme")["annual_schedule"] == [150000, 150000, 150000]


def test_load_contract():
    c = seed.load_contract("acme")
    assert c["annual_schedule"] == [100000, 150000, 200000]
    assert seed.load_contract("nope") is None
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_seed.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'data.seed'`)

- [ ] **Step 4: Write minimal implementation**

```python
# data/__init__.py
```

```python
# data/seed.py
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from core import database
from core.models import Agent, PolicyRule

DATA_DIR = Path(__file__).parent


def _load(name: str):
    return json.loads((DATA_DIR / name).read_text())


def load_contract(deal_id: str) -> dict | None:
    return _load("contracts.json").get(deal_id)


def seed(conn: sqlite3.Connection, demo_agent_name: str = "RevOps Finance Agent") -> Agent:
    # policy (replace existing so re-seed is idempotent)
    conn.execute("DELETE FROM policy_rules")
    for raw in _load("policy.json"):
        database.upsert_policy(conn, PolicyRule(**raw))
    # crm (mutable copy of the stale Salesforce state)
    for deal_id, record in _load("salesforce.json").items():
        database.upsert_crm(conn, deal_id, record)
    # demo agent (only if none exists)
    existing = conn.execute("SELECT id FROM agents LIMIT 1").fetchone()
    if existing:
        return database.get_agent(conn, existing["id"])
    agent = Agent(name=demo_agent_name)
    database.insert_agent(conn, agent)
    return agent


if __name__ == "__main__":
    c = database.get_connection()
    database.init_db(c)
    a = seed(c)
    print(f"seeded demo agent {a.id} ({a.name}); policy + CRM loaded")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_seed.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
git add data/ tests/test_seed.py
git commit -m "feat: mock contracts, stale CRM, DOA policy, seed"
```

---

### Task 8: FastAPI app + routes (the agent tool surface)

**Files:**
- Create: `api/main.py`, `api/routes.py`
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: everything above.
- Produces HTTP endpoints (consumed by Person A's agent + Person C's UI):
  - `POST /agents` `{name}` → Agent · `GET /agents/{id}` → Agent + `allowed_tools` · `GET /agents/{id}/skill.md` → text
  - `POST /sessions` `{agent_id, task, env_id?}` → Session
  - `POST /sessions/{id}/complete` `{accuracy, memories_used?, memories_created?, ...}` → `{session, agent}`
  - `GET /sessions` → list
  - `POST /memory` `{session_id, agent_id, type, content, metadata?}` → Memory (embeds content)
  - `GET /memory/retrieve?agent_id=&query=&type=&limit=` → list[Memory]
  - `POST /route_for_approval` `{amount_usd, change_type}` → `{route_to}`
  - `POST /crm/write` `{agent_id, deal_id, fields}` → 200 `{ok, crm}` or 403 (tier gate)
  - `GET /contracts/{deal_id}` → dict · `GET /crm/{deal_id}` → dict
  - `GET /policy` → list[PolicyRule] · `PUT /policy/{id}` `{condition?, route_to?}` → PolicyRule (bumps version)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_api.py
import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from core import database


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db = tmp_path / "api.db"
    monkeypatch.setenv("REVMEM_DB", str(db))
    monkeypatch.setattr("core.context.embed_text", lambda t: [1.0, 0.0])
    app = create_app()
    with TestClient(app) as c:
        yield c


def test_agent_and_skill(client):
    aid = client.post("/agents", json={"name": "A"}).json()["id"]
    got = client.get(f"/agents/{aid}").json()
    assert got["permission_tier"] == "observer"
    assert "write_crm" not in got["allowed_tools"]
    skill = client.get(f"/agents/{aid}/skill.md").text
    assert "RevOps Finance Agent" in skill


def test_route_for_approval(client):
    r = client.post("/route_for_approval",
                    json={"amount_usd": 0, "change_type": "schedule_change"})
    assert r.json()["route_to"] == "cfo"


def test_write_crm_denied_for_observer(client):
    aid = client.post("/agents", json={"name": "A"}).json()["id"]
    r = client.post("/crm/write",
                    json={"agent_id": aid, "deal_id": "acme",
                          "fields": {"annual_schedule": [100000, 150000, 200000]}})
    assert r.status_code == 403


def test_contracts_and_crm_served(client):
    assert client.get("/contracts/acme").json()["annual_schedule"] == [100000, 150000, 200000]
    assert client.get("/crm/acme").json()["annual_schedule"] == [150000, 150000, 150000]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_api.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'api.main'`)

- [ ] **Step 3: Write minimal implementation**

```python
# api/routes.py
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from core import context, database, governance, session
from core.models import Agent, Memory, MemoryType
from data import seed

router = APIRouter()


def _conn(request: Request):
    return request.app.state.conn


class CreateAgent(BaseModel):
    name: str


class StartSession(BaseModel):
    agent_id: str
    task: str
    env_id: str | None = None


class CompleteSession(BaseModel):
    accuracy: float
    memories_used: list[str] = []
    memories_created: list[str] = []


class CreateMemory(BaseModel):
    session_id: str
    agent_id: str
    type: str = MemoryType.PRICING_FIELD_RULE
    content: str
    metadata: dict = {}


class Discrepancy(BaseModel):
    amount_usd: float = 0.0
    change_type: str | None = None


class CrmWrite(BaseModel):
    agent_id: str
    deal_id: str
    fields: dict


class PolicyEdit(BaseModel):
    condition: dict | None = None
    route_to: str | None = None


@router.post("/agents")
def create_agent(body: CreateAgent, request: Request) -> dict:
    a = Agent(name=body.name)
    database.insert_agent(_conn(request), a)
    return a.model_dump(mode="json")


@router.get("/agents/{agent_id}")
def get_agent(agent_id: str, request: Request) -> dict:
    a = database.get_agent(_conn(request), agent_id)
    if not a:
        raise HTTPException(404, "unknown agent")
    out = a.model_dump(mode="json")
    out["allowed_tools"] = sorted(governance.allowed_tools(a.permission_tier))
    return out


@router.get("/agents/{agent_id}/skill.md", response_class=PlainTextResponse)
def skill_md(agent_id: str, request: Request) -> str:
    a = database.get_agent(_conn(request), agent_id)
    if not a:
        raise HTTPException(404, "unknown agent")
    return governance.generate_skill_md(a.permission_tier)


@router.post("/sessions")
def start_session(body: StartSession, request: Request) -> dict:
    s = session.start(_conn(request), body.agent_id, body.task, body.env_id)
    return s.model_dump(mode="json")


@router.post("/sessions/{session_id}/complete")
def complete_session(session_id: str, body: CompleteSession, request: Request) -> dict:
    conn = _conn(request)
    session.set_memories(conn, session_id, body.memories_used, body.memories_created)
    outcome = body.model_dump()
    s, a = session.complete(conn, session_id, outcome)
    return {"session": s.model_dump(mode="json"), "agent": a.model_dump(mode="json")}


@router.get("/sessions")
def list_sessions(request: Request) -> list[dict]:
    return [s.model_dump(mode="json") for s in database.list_sessions(_conn(request))]


@router.post("/memory")
def create_memory(body: CreateMemory, request: Request) -> dict:
    m = Memory(session_id=body.session_id, agent_id=body.agent_id, type=body.type,
               content=body.content, metadata=body.metadata,
               embedding=context.embed_text(body.content))
    database.insert_memory(_conn(request), m)
    return m.model_dump(mode="json")


@router.get("/memory/retrieve")
def retrieve_memory(agent_id: str, query: str, request: Request,
                    type: str | None = None, limit: int = 5) -> list[dict]:
    out = context.retrieve(_conn(request), agent_id, query, type, limit)
    return [m.model_dump(mode="json") for m in out]


@router.post("/route_for_approval")
def route_for_approval(body: Discrepancy, request: Request) -> dict:
    rules = database.list_policy(_conn(request))
    return {"route_to": governance.route(body.model_dump(), rules)}


@router.post("/crm/write")
def write_crm(body: CrmWrite, request: Request) -> dict:
    conn = _conn(request)
    a = database.get_agent(conn, body.agent_id)
    if not a:
        raise HTTPException(404, "unknown agent")
    if not governance.can_use(a.permission_tier, "write_crm"):
        raise HTTPException(403, f"tier {a.permission_tier} cannot write_crm — escalate instead")
    record = database.get_crm(conn, body.deal_id) or {}
    record.update(body.fields)
    database.upsert_crm(conn, body.deal_id, record)
    return {"ok": True, "crm": record}


@router.get("/contracts/{deal_id}")
def get_contract(deal_id: str) -> dict:
    c = seed.load_contract(deal_id)
    if not c:
        raise HTTPException(404, "unknown deal")
    return c


@router.get("/crm/{deal_id}")
def get_crm_record(deal_id: str, request: Request) -> dict:
    r = database.get_crm(_conn(request), deal_id)
    if not r:
        raise HTTPException(404, "unknown deal")
    return r


@router.get("/policy")
def get_policy(request: Request) -> list[dict]:
    return [r.model_dump(mode="json") for r in database.list_policy(_conn(request))]


@router.put("/policy/{policy_id}")
def edit_policy(policy_id: str, body: PolicyEdit, request: Request) -> dict:
    conn = _conn(request)
    r = database.get_policy(conn, policy_id)
    if not r:
        raise HTTPException(404, "unknown policy rule")
    if body.condition is not None:
        r.condition = body.condition
    if body.route_to is not None:
        r.route_to = body.route_to
    r.version += 1
    database.upsert_policy(conn, r)
    return r.model_dump(mode="json")
```

```python
# api/main.py
from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import router
from core import database
from data import seed


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        conn = database.get_connection(os.getenv("REVMEM_DB", str(database.DB_PATH)))
        database.init_db(conn)
        seed.seed(conn)
        app.state.conn = conn
        yield
        conn.close()

    app = FastAPI(title="RevMem API", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                       allow_headers=["*"])
    app.include_router(router)
    return app


app = create_app()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_api.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Full suite + commit**

```bash
uv run pytest -v
git add api/ tests/test_api.py
git commit -m "feat: FastAPI tool surface for agent + UI"
```

---

### Task 9: Local run + ngrok exposure

**Files:**
- Modify: `README.md` (create if absent)

**Interfaces:**
- Produces: documented commands to serve RevMem locally and expose it via ngrok for the hosted agent.

- [ ] **Step 1: Seed and run the API**

```bash
uv run python -m data.seed
uv run uvicorn api.main:app --host 0.0.0.0 --port 8000
```

- [ ] **Step 2: Expose via ngrok with a reserved domain (stable URL)**

```bash
# reserve a domain once in the ngrok dashboard, then:
ngrok http 8000 --domain=revmem-demo.ngrok.app
# Person A sets REVMEM_BASE_URL=https://revmem-demo.ngrok.app for the agent's tools
```

- [ ] **Step 3: Smoke-test through the tunnel**

```bash
curl -s https://revmem-demo.ngrok.app/contracts/acme -H "ngrok-skip-browser-warning: 1"
# expect the Acme order form JSON with annual_schedule [100000,150000,200000]
```

- [ ] **Step 4: Write the README run section and commit**

```markdown
## Run (local + ngrok)

1. `uv run python -m data.seed`
2. `uv run uvicorn api.main:app --host 0.0.0.0 --port 8000`
3. `ngrok http 8000 --domain=<your-reserved>.ngrok.app`
4. Set `REVMEM_BASE_URL` to the ngrok URL for the agent and the UI.

DB persists at `db/revmem.db`. Delete it to reset; `data.seed` reloads policy + CRM.
```

```bash
git add README.md
git commit -m "docs: local + ngrok run instructions"
```

---

## Self-Review

**Spec coverage** (against `ARCHITECTURE.md` Person B scope):
- models ✓ T1 · SQLite store ✓ T2 · reputation+tier ✓ T3 · session lifecycle+triggers ✓ T4 · retrieve+rerank ✓ T5 · policy routing+tier gating+SKILL.md ✓ T6 · mock data+seed ✓ T7 · FastAPI tool surface ✓ T8 · deploy/run (now ngrok) ✓ T9.
- Substrate updated Atlas → SQLite; hosting DO → ngrok, per the latest decision.
- `pgvector`/Atlas vector search intentionally dropped; semantic signal preserved via `embed_text` + Python cosine (gracefully degrades offline). Logged here so the cut is explicit, not silent.

**Placeholder scan:** none — every step has runnable code/commands and expected output. The `google-genai` embed signature is verified against `googleapis/python-genai` (`client.models.embed_content(model, contents, config=EmbedContentConfig(...))` → `response.embeddings[i].values`), with a deterministic offline fallback so tests never depend on the live API.

**Type consistency:** `retrieve`, `score_memory`, `route`, `allowed_tools`, `can_use`, `start`, `complete`, `set_memories`, `update_after_session`, `tier_for`, `compute` names/signatures are identical across the tasks that define and call them. Tool names match the Global Constraints list and the API routes.

**Note for the team:** the demo's reputation decimals are illustrative; this formula yields tiers OBSERVER → ANALYST → AUTONOMOUS across the three scripted sessions (verified by `test_demo_trajectory`), which is the property the demo depends on.
