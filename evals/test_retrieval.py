"""Tests for the retrieval-quality eval. Deterministic offline (hash-bag embed).

Run: python -m pytest evals/test_retrieval.py
"""

from __future__ import annotations

from evals import retrieval


def test_retrieval_surfaces_the_right_lesson():
    q = retrieval.evaluate_retrieval()
    assert q["hit@1"] == 1.0          # every task query surfaces its lesson first
    assert q["hit@3"] == 1.0
    assert q["mrr"] == 1.0
    for p in q["per_probe"]:
        assert p["rank"] == 1


def test_relevance_signal_improves_retrieval():
    abl = retrieval.relevance_ablation()
    # On a keyword-ambiguous query, the trusted lesson wins only with learned relevance.
    assert abl["learned_rank"] == 1
    assert abl["flat_rank"] == 2
    assert abl["rank_improved"] is True
    assert abl["mrr_lift"] == 0.5
