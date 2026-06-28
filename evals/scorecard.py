"""Summarize REAL session outcomes into a continual-learning scorecard.

Single source of truth for "did the agent get better across sessions", consumed by:
  - the CLI end-screen (``cli/run.py``) after a multi-session live run
  - the live harness (``evals/live.py``) reading persisted outcomes from API/DB

Input: an ordered list of session dicts, each with an ``outcome`` dict holding the
keys the runner logs - accuracy, material_caught, material_total,
false_escalations, routing_accuracy. Sessions without a numeric ``accuracy`` are
skipped (e.g. mock/empty outcomes), so this is safe to call on any results list.

Pure stdlib - no core/pydantic import - so the CLI stays light.
"""

from __future__ import annotations

from typing import Any


def _num(v: Any) -> float | None:
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _recall(outcome: dict) -> float | None:
    caught, total = _num(outcome.get("material_caught")), _num(outcome.get("material_total"))
    if caught is None or not total:
        return None
    return round(caught / total, 3)


def _point(seq_index: int, session: dict) -> dict:
    outcome = session.get("outcome") or {}
    return {
        "index": seq_index,
        "session": session.get("session_number", session.get("run", session.get("session", seq_index))),
        "deal": session.get("deal"),
        "tier": session.get("tier"),
        "reputation": _num(session.get("reputation")),
        "accuracy": _num(outcome.get("accuracy")),
        "material_recall": _recall(outcome),
        "material_caught": _num(outcome.get("material_caught")),
        "material_total": _num(outcome.get("material_total")),
        "false_escalations": _num(outcome.get("false_escalations")),
        "routing_accuracy": _num(outcome.get("routing_accuracy")),
    }


def summarize_sessions(sessions: list[dict]) -> dict:
    """Build a learning curve + first->last deltas from real per-session outcomes."""
    points: list[dict] = []
    for s in sessions:
        p = _point(len(points) + 1, s)
        if p["accuracy"] is None:  # unscored / mock session - skip
            continue
        points.append(p)

    summary: dict[str, Any] = {"n": len(points), "curve": points, "improved": False, "deltas": {}}
    if len(points) < 2:
        return summary

    first, last = points[0], points[-1]

    def delta(key: str) -> float | None:
        a, b = first.get(key), last.get(key)
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return round(b - a, 3)
        return None

    summary["first"] = first
    summary["last"] = last
    summary["deltas"] = {
        "accuracy": delta("accuracy"),
        "false_escalations": delta("false_escalations"),
        "material_recall": delta("material_recall"),
        "reputation": delta("reputation"),
    }
    accs = [p["accuracy"] for p in points]
    summary["monotonic"] = accs == sorted(accs)
    fe = summary["deltas"]["false_escalations"]
    summary["improved"] = last["accuracy"] > first["accuracy"] or (fe is not None and fe < 0)
    return summary
