"""Read REAL logged session outcomes from the running system and summarize them.

Two sources, both work without standing up extra infra for the demo:
  - DB:  the SQLite file the API writes (``REVMEM_DB`` or ``db/revmem.db``)
  - API: ``GET /sessions`` on a running RevMem service (``REVMEM_BASE_URL``)

This turns the *actual* persisted learning history into the same scorecard the
CLI shows, so the curve reflects what really happened in live runs, not the
modeled behaviors in ``harness.py``.

Note: the persisted ``Session`` carries the outcome (accuracy, material_caught,
material_total, false_escalations, routing_accuracy) but not deal/tier/reputation
(those live on the agent), so a DB/API curve shows the task-quality trajectory.
"""

from __future__ import annotations

import json
import os
import sqlite3
import urllib.request
from typing import Any

from evals.scorecard import summarize_sessions


_FINISHED = {"completed", "failed"}


def _finished(sessions: list[dict]) -> list[dict]:
    """Finished sessions with an outcome, in chronological order.

    Includes ``failed`` (accuracy < success threshold), not just ``completed`` -
    the S1 cold-start failure is the start of the learning curve, not noise.
    """
    done = [s for s in sessions if s.get("status") in _FINISHED and s.get("outcome")]
    return sorted(done, key=lambda s: s.get("started_at") or "")


def read_outcomes_from_db(db_path: str | None = None, agent_id: str | None = None) -> list[dict]:
    """Read completed sessions straight from the SQLite file (no server needed)."""
    from core import database  # lazy: keeps CLI import light

    path = db_path or os.getenv("REVMEM_DB", str(database.DB_PATH))
    conn = database.get_connection(path)
    try:
        sessions = database.list_sessions(conn, agent_id)
    except sqlite3.OperationalError:
        # Pointed at a file with no RevMem schema yet -> treat as "no sessions".
        return []
    finally:
        conn.close()
    return _finished([s.model_dump(mode="json") for s in sessions])


def read_outcomes_from_api(base_url: str | None = None, agent_id: str | None = None) -> list[dict]:
    """Read completed sessions from a running RevMem API via GET /sessions."""
    base = (base_url or os.getenv("REVMEM_BASE_URL", "")).rstrip("/")
    if not base:
        raise ValueError("REVMEM_BASE_URL is not set and no base_url was passed")
    req = urllib.request.Request(
        f"{base}/sessions", headers={"ngrok-skip-browser-warning": "1"}
    )
    with urllib.request.urlopen(req) as resp:  # noqa: S310 - trusted local/ngrok URL
        sessions = json.loads(resp.read())
    if agent_id:
        sessions = [s for s in sessions if s.get("agent_id") == agent_id]
    return _finished(sessions)


def live_summary(source: str = "db", **kwargs: Any) -> dict:
    """Read real outcomes from ``db`` or ``api`` and summarize the learning curve."""
    if source == "db":
        sessions = read_outcomes_from_db(**kwargs)
    elif source == "api":
        sessions = read_outcomes_from_api(**kwargs)
    else:
        raise ValueError(f"unknown source {source!r} (expected 'db' or 'api')")
    summary = summarize_sessions(sessions)
    summary["source"] = f"live-{source}"
    return summary
