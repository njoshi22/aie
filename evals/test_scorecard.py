"""Tests for the shared session summarizer. Run: python -m pytest evals/test_scorecard.py"""

from __future__ import annotations

from evals.scorecard import summarize_sessions


def _session(acc, caught, total, fe):
    return {"outcome": {"accuracy": acc, "material_caught": caught,
                        "material_total": total, "false_escalations": fe}}


def test_curve_tracks_improvement_and_deltas():
    s = summarize_sessions([_session(0.0, 0, 1, 1), _session(1.0, 1, 1, 0), _session(1.0, 2, 2, 0)])
    assert s["n"] == 3
    assert s["improved"] is True
    assert s["monotonic"] is True
    assert s["deltas"]["accuracy"] == 1.0
    assert s["deltas"]["false_escalations"] == -1
    assert s["deltas"]["material_recall"] == 1.0
    assert s["curve"][0]["material_recall"] == 0.0
    assert s["curve"][-1]["material_recall"] == 1.0


def test_skips_unscored_sessions():
    # empty/mock outcomes have no numeric accuracy and must be dropped
    s = summarize_sessions([{"outcome": {}}, _session(0.5, 1, 2, 0), {"outcome": {"accuracy": "2/2"}}])
    assert s["n"] == 1
    assert s["deltas"] == {}        # < 2 scored sessions -> no deltas, no crash


def test_empty_is_safe():
    s = summarize_sessions([])
    assert s["n"] == 0 and s["improved"] is False


def test_no_false_improvement_when_flat():
    s = summarize_sessions([_session(1.0, 1, 1, 0), _session(1.0, 1, 1, 0)])
    assert s["deltas"]["accuracy"] == 0.0
    assert s["improved"] is False
