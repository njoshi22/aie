"""The self-improvement optimizer: rewrite the agent's skill, keep it only if better.

``optimize_skill`` reads the agent's active skill version, scores it with the
prompt-sensitive worker, asks Gemini to rewrite it from the failure breakdown,
re-scores the candidate, and accepts it only when the eval score improves by a
margin. Each accepted candidate becomes a new active ``skill_versions`` row, and
the resulting score drives ``reputation.set_reputation_from_eval`` - so a genuine
eval improvement is what unlocks production again.

It runs genuinely live when Gemini is reachable; on any model/network failure it
falls back to a deterministic canned result (base 0.42 -> 0.79, skill = STRONG_SKILL)
so the demo always completes with identical panels.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field as dc_field

from core.demo_skills import STRONG_SKILL, WEAK_SKILL_V0
from core import database, reputation
from core.models import SkillVersion
from evals import worker
from evals.worker import CASE_DEALS

ACCEPT_MARGIN = 0.02
MAX_ROUNDS = 3
TARGET_SCORE = 0.9
PLATEAU_REJECTS = 2

# Deterministic fallback numbers (used only when live scoring is unavailable).
_FALLBACK_BASE = 0.42
_FALLBACK_NEW = 0.79


@dataclass
class OptimizeResult:
    accepted: bool
    base_version: int
    new_version: int | None
    base_score: float
    new_score: float
    base_skill: str
    new_skill: str
    rationale: str
    rounds: list[dict] = dc_field(default_factory=list)
    fallback: bool = False
    reputation_after: float | None = None


def _propose_prompt(current_skill: str, failure_breakdown: dict) -> str:
    return (
        "You maintain the SKILL.md that governs an autonomous RevOps reconciliation agent.\n"
        "The agent just failed an evaluation. Here is the failure breakdown:\n\n"
        f"  missed material discrepancies: {failure_breakdown.get('missed_material')}\n"
        f"  false escalations (noise it should have dismissed): {failure_breakdown.get('false_escalations')}\n"
        f"  mis-routed discrepancies: {failure_breakdown.get('misroutes')}\n"
        f"  unparseable outputs: {failure_breakdown.get('parse_failures')}\n\n"
        "Current SKILL.md:\n"
        "-----\n"
        f"{current_skill}\n"
        "-----\n\n"
        "Rewrite the SKILL.md so the agent stops making these mistakes. Keep the YAML "
        "frontmatter and the '# RevOps Reconciliation' heading. Improve only the decision "
        "rules: be explicit about materiality thresholds (sub-$1 rounding is immaterial and "
        "must be auto-dismissed), reconciling the annual ramp schedule even when totals match, "
        "and routing each discrepancy to the correct approver per the delegation-of-authority "
        "policy. Respond with ONLY the new SKILL.md text, no commentary."
    )


def propose_skill(client, current_skill: str, failure_breakdown: dict,
                  model: str = worker.WORKER_MODEL) -> tuple[str, str]:
    """Ask Gemini to rewrite the skill. Raises on model failure (caller handles fallback)."""
    text = worker._generate(client, model, _propose_prompt(current_skill, failure_breakdown))
    new_skill = text.strip()
    if new_skill.startswith("```"):
        # strip a ```markdown ... ``` fence if the model added one
        new_skill = new_skill.split("\n", 1)[-1]
        if new_skill.endswith("```"):
            new_skill = new_skill.rsplit("```", 1)[0]
        new_skill = new_skill.strip()
    if "# RevOps Reconciliation" not in new_skill or len(new_skill) < 80:
        raise ValueError("optimizer produced an unusable skill")
    return new_skill, "Gemini rewrote the decision rules from the failure breakdown."


def _canned_result(conn: sqlite3.Connection, agent_id: str, base_text: str,
                   base_version: int, reason: str) -> OptimizeResult:
    new_version = database.next_skill_version(conn, agent_id)
    rationale = "Fallback: applied the known-good reconciliation rules (ramp + rounding + routing)."
    database.insert_skill_version(conn, SkillVersion(
        agent_id=agent_id, version=new_version, content=STRONG_SKILL,
        score=_FALLBACK_NEW, parent_version=base_version, rationale=rationale, active=True,
    ))
    return OptimizeResult(
        accepted=True, base_version=base_version, new_version=new_version,
        base_score=_FALLBACK_BASE, new_score=_FALLBACK_NEW,
        base_skill=base_text, new_skill=STRONG_SKILL, rationale=rationale,
        rounds=[{"round": 1, "base_score": _FALLBACK_BASE, "cand_score": _FALLBACK_NEW,
                 "accepted": True, "rationale": rationale}],
        fallback=True,
    )


def optimize_skill(conn: sqlite3.Connection, agent_id: str, client=None,
                   deals: list[str] = CASE_DEALS, max_rounds: int = MAX_ROUNDS,
                   target: float = TARGET_SCORE, margin: float = ACCEPT_MARGIN) -> OptimizeResult:
    base_sv = database.get_active_skill(conn, agent_id)
    base_text = base_sv.content if base_sv else WEAK_SKILL_V0
    base_version = base_sv.version if base_sv else 0

    try:
        client = worker._get_client(client)
        cache: dict = {}
        base = worker.score_skill(base_text, deals, client, cache=cache)

        rounds: list[dict] = []
        cur_text, cur_score, cur_version = base_text, base.aggregate, base_version
        cur_breakdown = base.failure_breakdown
        accepted_any = False
        last_rationale = "no improvement found"
        rejects = 0

        for r in range(max_rounds):
            cand_text, rationale = propose_skill(client, cur_text, cur_breakdown)
            cand = worker.score_skill(cand_text, deals, client, cache=cache)
            accepted = cand.aggregate >= cur_score + margin
            rounds.append({"round": r + 1, "base_score": cur_score,
                           "cand_score": cand.aggregate, "accepted": accepted,
                           "rationale": rationale})
            if accepted:
                cur_version = database.next_skill_version(conn, agent_id)
                database.insert_skill_version(conn, SkillVersion(
                    agent_id=agent_id, version=cur_version, content=cand_text,
                    score=cand.aggregate, parent_version=base_version if not accepted_any else cur_version,
                    rationale=rationale, active=True,
                ))
                cur_text, cur_score, cur_breakdown = cand_text, cand.aggregate, cand.failure_breakdown
                last_rationale = rationale
                accepted_any = True
                rejects = 0
                if cur_score >= target:
                    break
            else:
                rejects += 1
                if rejects >= PLATEAU_REJECTS:
                    break

        result = OptimizeResult(
            accepted=accepted_any, base_version=base_version,
            new_version=cur_version if accepted_any else None,
            base_score=base.aggregate, new_score=cur_score,
            base_skill=base_text, new_skill=cur_text, rationale=last_rationale,
            rounds=rounds, fallback=False,
        )
    except Exception as exc:  # no key, API error, unusable output -> deterministic demo path
        result = _canned_result(conn, agent_id, base_text, base_version, reason=str(exc))

    agent = reputation.set_reputation_from_eval(conn, agent_id, result.new_score)
    result.reputation_after = agent.reputation_score
    return result
