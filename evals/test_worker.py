"""Tests for the prompt-sensitive worker scorer.

The offline tests use a fake client (no network) to prove the worker/grader
plumbing: a gold-perfect transcript outscores an escalate-everything one, parse
failures score low, and the sha256 cache prevents re-scoring identical skills.
The live test (gated on GEMINI_API_KEY) proves real prompt sensitivity: the
strong skill beats the weak v0 by a wide margin.
"""

from __future__ import annotations

import json
import os

import pytest

from core.demo_skills import STRONG_SKILL, WEAK_SKILL_V0
from evals import worker
from evals.gold import build_gold


class _FakeResponse:
    def __init__(self, text: str):
        self.text = text


class _FakeModels:
    def __init__(self, outer):
        self._outer = outer

    def generate_content(self, model=None, contents=None, config=None):
        self._outer.calls += 1
        return _FakeResponse(self._outer.text_for(contents))


class _FakeClient:
    """Returns a fixed transcript regardless of prompt; counts calls."""

    def __init__(self, text: str):
        self._text = text
        self.calls = 0
        self.models = _FakeModels(self)

    def text_for(self, _contents):
        return self._text


def _perfect_output(deal: str) -> str:
    fields = []
    for g in build_gold(deal):
        if g.material:
            fields.append({"field": g.field, "match": False, "materiality": "material",
                           "recommended_action": "escalate", "route_to": g.expected_route})
        else:
            fields.append({"field": g.field, "match": False, "materiality": "immaterial",
                           "recommended_action": "auto_dismiss", "route_to": None})
    return json.dumps({"deal_id": deal, "fields_compared": fields})


def _escalate_everything_output(deal: str) -> str:
    fields = [{"field": g.field, "match": False, "materiality": "material",
               "recommended_action": "escalate", "route_to": "cfo"}
              for g in build_gold(deal)]
    return json.dumps({"deal_id": deal, "fields_compared": fields})


def test_perfect_beats_escalate_everything():
    deal = "acme"
    good = worker.score_skill("skill", deals=[deal], client=_FakeClient(_perfect_output(deal)))
    bad = worker.score_skill("skill", deals=[deal], client=_FakeClient(_escalate_everything_output(deal)))
    assert good.aggregate > bad.aggregate
    assert good.aggregate >= 0.99
    assert bad.failure_breakdown["false_escalations"]  # rounding got escalated


def test_parse_failure_scores_low_and_is_flagged():
    res = worker.score_skill("skill", deals=["acme"], client=_FakeClient("not json at all"))
    assert res.per_case[0].parsed is False
    assert res.failure_breakdown["parse_failures"] == 1
    # No parsed decisions -> every material discrepancy is missed; far below a
    # gold-perfect transcript (1.0). Immaterial fields score by omission, so the
    # floor is data-dependent, not 0.
    assert res.aggregate <= 0.5
    assert res.failure_breakdown["missed_material"]


def test_cache_prevents_rescore():
    client = _FakeClient(_perfect_output("acme"))
    cache: dict = {}
    worker.score_skill("skill-A", deals=["acme"], client=client, cache=cache)
    assert client.calls == 1
    worker.score_skill("skill-A", deals=["acme"], client=client, cache=cache)
    assert client.calls == 1  # served from cache
    worker.score_skill("skill-B", deals=["acme"], client=client, cache=cache)
    assert client.calls == 2  # different skill text -> new call


def test_build_worker_prompt_has_schema_and_data():
    prompt = worker._build_worker_prompt(WEAK_SKILL_V0, "acme")
    assert "fields_compared" in prompt
    assert "recommended_action" in prompt
    assert "SIGNED CONTRACT" in prompt


@pytest.mark.skipif(not os.getenv("GEMINI_API_KEY"), reason="needs GEMINI_API_KEY for live scoring")
def test_strong_skill_beats_weak_live():
    cache: dict = {}
    weak = worker.score_skill(WEAK_SKILL_V0, cache=cache)
    strong = worker.score_skill(STRONG_SKILL, cache=cache)
    assert strong.aggregate >= weak.aggregate + 0.15
