"""Prompt-sensitive worker scorer - the optimizer's objective function.

The offline harness (``evals.harness.run``) grades hardcoded ``MODELED`` decisions
that ignore the skill prompt, so it cannot tell a good skill from a bad one. This
module closes that gap: given a skill prompt, it asks a cheap model (Gemini Flash,
temperature 0) to actually reconcile each demo deal, parses the output with the
same ``decisions_from_output`` the live runner uses, and grades it with the same
``grade``/``build_gold``. A better skill therefore yields a higher score - the
signal the optimizer hill-climbs on.

Determinism: temperature 0 plus an sha256 cache keyed by (model, deal, skill_text)
so identical skill text is never re-scored within an optimize loop.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass

from core.demo_skills import STRONG_SKILL, WEAK_SKILL_V0  # noqa: F401 (re-exported for tests)
from evals.behaviors import decisions_from_output
from evals.gold import _load, build_gold
from evals.grade import Scorecard, grade

WORKER_MODEL = "gemini-3.5-flash"
CASE_DEALS = ["acme", "globex"]


@dataclass
class CaseResult:
    deal: str
    scorecard: Scorecard
    raw_output: str
    parsed: bool                 # decisions_from_output yielded >=1 decision


@dataclass
class WorkerScore:
    aggregate: float             # mean Scorecard.accuracy across cases
    per_case: list[CaseResult]
    failure_breakdown: dict      # {missed_material, false_escalations, misroutes, parse_failures}


def _get_client(client=None):
    if client is not None:
        return client
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY required for worker scoring (or pass a client)")
    from google import genai
    return genai.Client(api_key=key)


def _generate(client, model: str, prompt: str) -> str:
    from google.genai import types

    resp = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0),
    )
    return resp.text or ""


def _build_worker_prompt(skill_text: str, deal: str) -> str:
    contract, crm, policy = _load(deal)
    return (
        skill_text
        + "\n\n---\n\n"
        + "Reconcile the signed contract against the CRM record by applying the rules above.\n\n"
        + f"SIGNED CONTRACT:\n{json.dumps(contract, indent=2)}\n\n"
        + f"CRM RECORD:\n{json.dumps(crm, indent=2)}\n\n"
        + f"DELEGATION OF AUTHORITY POLICY:\n{json.dumps(policy, indent=2)}\n\n"
        + "Compare every pricing field. Respond with ONLY a JSON object (no prose, no code fence "
          "is required) in EXACTLY this schema:\n"
        + '{\n'
          '  "deal_id": "...",\n'
          '  "fields_compared": [\n'
          '    {"field": "annual_schedule_usd", "match": false, "materiality": "material", '
          '"diff_usd": 0, "recommended_action": "escalate", "route_to": "controller", "reasoning": "..."}\n'
          '  ]\n'
          '}\n'
        + "Constraints: recommended_action must be one of escalate | auto_dismiss | auto_resolve. "
          "route_to must be one of am | controller | cfo | cfo_cco | null. "
          "Include exactly one entry per field you compared.\n"
    )


def _failure_breakdown(per_case: list[CaseResult]) -> dict:
    missed: list[str] = []
    false_esc: list[str] = []
    misroutes: list[str] = []
    parse_failures = 0
    for c in per_case:
        if not c.parsed:
            parse_failures += 1
        for note in c.scorecard.notes:
            head = note.split(":", 1)[0].strip()
            if "MISSED material" in note:
                missed.append(head)
            elif "false escalation" in note:
                false_esc.append(head)
            elif "routed to" in note:
                misroutes.append(note.strip())
    return {
        "missed_material": missed,
        "false_escalations": false_esc,
        "misroutes": misroutes,
        "parse_failures": parse_failures,
    }


def _run_case(skill_text: str, deal: str, client, model: str, cache: dict | None) -> CaseResult:
    key = hashlib.sha256(f"{model}\x00{deal}\x00{skill_text}".encode()).hexdigest()
    if cache is not None and key in cache:
        raw = cache[key]
    else:
        raw = _generate(client, model, _build_worker_prompt(skill_text, deal))
        if cache is not None:
            cache[key] = raw
    decisions = decisions_from_output(raw)   # no MODELED fallback: unparseable scores low
    sc = grade(deal, decisions, build_gold(deal))
    return CaseResult(deal=deal, scorecard=sc, raw_output=raw, parsed=bool(decisions))


def score_skill(skill_text: str, deals: list[str] = CASE_DEALS, client=None,
                model: str = WORKER_MODEL, cache: dict | None = None) -> WorkerScore:
    """Score a skill prompt by reconciling each deal and grading the result."""
    client = _get_client(client)
    per_case = [_run_case(skill_text, d, client, model, cache) for d in deals]
    accs = [c.scorecard.accuracy for c in per_case]
    aggregate = sum(accs) / len(accs) if accs else 0.0
    return WorkerScore(
        aggregate=round(aggregate, 3),
        per_case=per_case,
        failure_breakdown=_failure_breakdown(per_case),
    )
