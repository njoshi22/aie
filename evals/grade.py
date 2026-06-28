"""Grade an agent's decisions for one session against the gold labels.

A ``Decision`` is what the agent actually did with a field:
    escalate / reconcile  -> it acted on the discrepancy (caught it)
    dismiss               -> it judged the discrepancy immaterial
    miss                  -> it never noticed (or no decision was emitted)

``grade`` turns a set of decisions + gold into a ``Scorecard`` whose ``.outcome``
is exactly the dict ``revmem_client.complete_session`` expects - so the harness
output can replace the hardcoded ``scenario["expected"]`` in the runner.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field

from evals.gold import GoldItem

CAUGHT_ACTIONS = {"escalate", "reconcile", "flag"}
ESCALATING_ACTIONS = {"escalate", "reconcile", "flag"}  # actions that touch an approver/CRM


@dataclass
class Decision:
    field: str
    action: str                  # escalate | reconcile | flag | dismiss | miss
    route_to: str | None = None


@dataclass
class Scorecard:
    deal: str
    material_total: int = 0
    material_caught: int = 0
    routing_correct: int = 0
    immaterial_total: int = 0
    immaterial_correct: int = 0
    false_escalations: int = 0
    notes: list[str] = dc_field(default_factory=list)

    @property
    def material_recall(self) -> float:
        return self.material_caught / self.material_total if self.material_total else 0.0

    @property
    def routing_accuracy(self) -> float:
        return self.routing_correct / self.material_caught if self.material_caught else 0.0

    @property
    def accuracy(self) -> float:
        """Composite 0..1 over the interesting fields (material + immaterial).

        A material field scores only when caught AND routed correctly; an
        immaterial field scores when correctly dismissed. Plain matches are
        excluded from the denominator (they are trivial)."""
        total = self.material_total + self.immaterial_total
        if not total:
            return 0.0
        # Full credit for caught-and-correctly-routed; half credit for
        # caught-but-misrouted (noticed the issue, wrong approver).
        material_pts = self.routing_correct + 0.5 * (self.material_caught - self.routing_correct)
        return max(0.0, min(1.0, (material_pts + self.immaterial_correct) / total))

    @property
    def outcome(self) -> dict:
        """The dict shape complete_session/reputation consume."""
        return {
            "accuracy": round(self.accuracy, 3),
            "material_caught": self.material_caught,
            "material_total": self.material_total,
            "false_escalations": self.false_escalations,
            "routing_accuracy": round(self.routing_accuracy, 3),
        }


def grade(deal: str, decisions: list[Decision], gold: list[GoldItem]) -> Scorecard:
    by_field = {d.field: d for d in decisions}
    sc = Scorecard(deal=deal)

    for g in gold:
        d = by_field.get(g.field)
        if g.material:
            sc.material_total += 1
            if d and d.action in CAUGHT_ACTIONS:
                sc.material_caught += 1
                if d.route_to == g.expected_route:
                    sc.routing_correct += 1
                else:
                    sc.notes.append(
                        f"{g.field}: routed to {d.route_to or 'none'}, expected {g.expected_route}"
                    )
            else:
                sc.notes.append(f"{g.field}: MISSED material discrepancy")
        else:
            sc.immaterial_total += 1
            if d and d.action in ESCALATING_ACTIONS:
                sc.false_escalations += 1
                sc.notes.append(f"{g.field}: false escalation of an immaterial diff")
            else:
                sc.immaterial_correct += 1

    # Penalize escalating a field that gold considers a clean match (not in gold
    # discrepancy set at all) - defensive against hallucinated discrepancies.
    gold_fields = {g.field for g in gold}
    for d in decisions:
        if d.field not in gold_fields and d.action in ESCALATING_ACTIONS:
            sc.false_escalations += 1
            sc.notes.append(f"{d.field}: false escalation (no discrepancy exists)")

    return sc
