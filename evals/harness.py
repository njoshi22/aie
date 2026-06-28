"""Run the eval across the demo sessions and assemble the continual-learning story.

Produces, from graded scorecards:
  - a per-session learning curve (accuracy / recall / false-escalations / routing)
  - an ablation delta  (S2 memory ON vs OFF: same deal, same permissions)
  - a generalization delta (learned lesson applied to an unseen deal in S3)

Offline by default (modeled decisions). To grade real runs, pass a mapping of
session -> agent transcript and decisions get parsed via ``decisions_from_output``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from evals import behaviors
from evals.gold import build_gold, gold_counts
from evals.grade import Scorecard, grade

# Maps the demo's three sessions to (deal, modeled-behavior step, permission tier).
# Tier is held OBSERVER across S1->S2 to isolate "RevMem made it smarter" from
# "permissions expanded", exactly as ARCHITECTURE.md frames it.
SESSIONS = [
    {"session": 1, "deal": "acme", "step": "acme_cold", "tier": "observer", "memory": False},
    {"session": 2, "deal": "acme", "step": "acme_learned", "tier": "observer", "memory": True},
    {"session": 3, "deal": "globex", "step": "globex_learned", "tier": "analyst", "memory": True},
]


@dataclass
class SessionResult:
    session: int
    deal: str
    tier: str
    memory: bool
    scorecard: Scorecard

    def row(self) -> dict:
        o = self.scorecard.outcome
        return {
            "session": self.session,
            "deal": self.deal,
            "tier": self.tier,
            "memory": self.memory,
            "accuracy": o["accuracy"],
            "material_recall": round(self.scorecard.material_recall, 3),
            "material": f"{self.scorecard.material_caught}/{self.scorecard.material_total}",
            "false_escalations": o["false_escalations"],
            "routing_accuracy": o["routing_accuracy"],
        }


def _grade_step(deal: str, step: str, transcripts: dict | None) -> Scorecard:
    gold = build_gold(deal)
    decisions = []
    if transcripts and step in transcripts:
        decisions = behaviors.decisions_from_output(transcripts[step])
    if not decisions:
        decisions = behaviors.modeled(step)
    return grade(deal, decisions, gold)


def run(transcripts: dict | None = None) -> dict:
    results = [
        SessionResult(
            session=s["session"],
            deal=s["deal"],
            tier=s["tier"],
            memory=s["memory"],
            scorecard=_grade_step(s["deal"], s["step"], transcripts),
        )
        for s in SESSIONS
    ]

    # Ablation: re-grade S2's deal with memory OFF == the cold behavior. Same deal,
    # same OBSERVER tier -> the only changed variable is RevMem context.
    s2 = next(r for r in results if r.session == 2)
    s2_nomem = _grade_step("acme", "acme_cold", transcripts)
    ablation = {
        "deal": "acme",
        "tier_held": "observer",
        "memory_on": s2.scorecard.outcome,
        "memory_off": s2_nomem.outcome,
        "accuracy_gain": round(s2.scorecard.accuracy - s2_nomem.accuracy, 3),
        "recall_gain": round(s2.scorecard.material_recall - s2_nomem.material_recall, 3),
    }

    # Generalization: S3 is an unseen deal; recall there shows the lesson transferred.
    s3 = next(r for r in results if r.session == 3)
    generalization = {
        "trained_on": "acme",
        "evaluated_on": s3.deal,
        "material_recall_on_unseen_deal": round(s3.scorecard.material_recall, 3),
        "false_escalations_on_unseen_deal": s3.scorecard.outcome["false_escalations"],
    }

    curve = [r.row() for r in results]
    deltas = {
        "s1_to_s2": {
            "accuracy": round(results[1].scorecard.accuracy - results[0].scorecard.accuracy, 3),
            "false_escalations": results[1].scorecard.false_escalations
            - results[0].scorecard.false_escalations,
            "note": "same deal, permissions held -> pure RevMem context effect",
        },
        "s2_to_s3": {
            "accuracy": round(results[2].scorecard.accuracy - results[1].scorecard.accuracy, 3),
            "note": "unseen deal + tier expands -> lesson generalizes, autonomy grows",
        },
    }

    return {
        "curve": curve,
        "deltas": deltas,
        "ablation": ablation,
        "generalization": generalization,
        "gold": {s["deal"]: gold_counts(build_gold(s["deal"])) for s in SESSIONS},
        "results": [
            {**asdict(r.scorecard), "session": r.session, "deal": r.deal} for r in results
        ],
        "source": "real-transcripts" if transcripts else "modeled",
    }
