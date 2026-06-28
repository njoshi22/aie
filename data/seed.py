from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from core import database
from core.models import Agent, PolicyRule

DATA_DIR = Path(__file__).parent


def _load(name: str) -> Any:
    return json.loads((DATA_DIR / name).read_text())


def load_contract(deal_id: str) -> dict[str, Any] | None:
    return _load("contracts.json").get(deal_id)


def seed(conn: sqlite3.Connection, demo_agent_name: str = "RevOps Finance Agent") -> Agent:
    # Reset mutable demo state so each (re)seed is a true cold start.
    conn.execute("DELETE FROM approvals")
    conn.execute("DELETE FROM memories")
    conn.execute("DELETE FROM sessions")
    conn.commit()
    # policy (replace existing so re-seed is idempotent)
    conn.execute("DELETE FROM policy_rules")
    raw_policy = _load("policy.json")
    rules = raw_policy["rules"] if isinstance(raw_policy, dict) else raw_policy
    for raw in rules:
        database.upsert_policy(conn, PolicyRule(**raw))
    # crm (mutable copy of the stale Salesforce state)
    for deal_id, record in _load("salesforce.json").items():
        database.upsert_crm(conn, deal_id, record)
    # demo agent: reset to cold start (keep the same id so re-seed is idempotent),
    # so reputation, tier, and session counts replay from observer/0.1 each time.
    existing = conn.execute("SELECT id FROM agents LIMIT 1").fetchone()
    if existing:
        agent = Agent(id=existing["id"], name=demo_agent_name)
        database.update_agent(conn, agent)
        return agent
    agent = Agent(name=demo_agent_name)
    database.insert_agent(conn, agent)
    return agent


if __name__ == "__main__":
    c = database.get_connection()
    database.init_db(c)
    a = seed(c)
    print(f"seeded demo agent {a.id} ({a.name}); policy + CRM loaded")
