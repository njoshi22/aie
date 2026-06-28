"""Gold labels - the ground truth a session is graded against.

Derived from the canonical ``data`` files the API serves, so labels never drift
from the demo data. For each comparable field we compute the contract-vs-CRM diff
and classify it via the DOA policy:

    none      fields match (no discrepancy)
    dismiss   discrepancy below materiality (sub-$1 rounding -> DOA-001)
    escalate  material discrepancy -> routed to an approver by policy

Materiality and routing come straight from ``policy.json`` so the grader and the
governance engine agree on what "correct" means.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
DEAL_DESK_MAX_DISCOUNT_PCT = 20  # contract discount above this exceeds authority


@dataclass
class GoldItem:
    field: str
    contract: object
    crm: object
    diff_usd: float
    change_type: str | None      # schedule_change | discount_over_authority | ...
    material: bool               # True iff a correct agent must escalate it
    expected_action: str         # none | dismiss | escalate
    expected_route: str | None   # am | controller | cfo | cfo_cco | None


def _load(deal: str) -> tuple[dict, dict, dict]:
    contracts = json.loads((DATA_DIR / "contracts.json").read_text())
    crm_records = json.loads((DATA_DIR / "salesforce.json").read_text())
    policy = json.loads((DATA_DIR / "policy.json").read_text())
    return contracts[deal], crm_records[deal], policy


def _numeric_ok(cond: dict, diff_usd: float) -> bool:
    if "min_diff_usd" in cond and diff_usd < cond["min_diff_usd"]:
        return False
    if "max_diff_usd" in cond and diff_usd > cond["max_diff_usd"]:
        return False
    return True


def resolve_route(policy: dict, change_type: str | None, diff_usd: float) -> tuple[str, str | None]:
    """Walk the DOA policy and return (action, route_to) for a discrepancy.

    Two-pass waterfall so a categorical flag (e.g. ``discount_over_authority``)
    is never swallowed by a generic dollar-threshold rule:
      1. rules that explicitly name ``change_types`` and match this change_type
      2. numeric-only rules (no ``change_types``) matched by dollar bounds
    Within each pass, the first matching rule wins.
    """
    rules = policy.get("rules", [])
    for rule in rules:
        cond = rule.get("condition", {})
        types = cond.get("change_types")
        if types and change_type in types and _numeric_ok(cond, diff_usd):
            return rule.get("action", "escalate"), rule.get("route_to")
    for rule in rules:
        cond = rule.get("condition", {})
        if cond.get("change_types"):
            continue
        if _numeric_ok(cond, diff_usd):
            return rule.get("action", "escalate"), rule.get("route_to")
    return "escalate", "cfo"  # fail safe: unknown -> highest approver


def build_gold(deal: str) -> list[GoldItem]:
    contract, crm, policy = _load(deal)
    items: list[GoldItem] = []

    def add(field, change_type, diff_usd):
        action, route = resolve_route(policy, change_type, diff_usd)
        material = action == "escalate"
        items.append(
            GoldItem(
                field=field,
                contract=contract.get(field),
                crm=crm.get(field),
                diff_usd=diff_usd,
                change_type=change_type if (material or action == "dismiss") else None,
                material=material,
                expected_action=action if action in ("dismiss", "escalate") else "dismiss",
                expected_route=route,
            )
        )

    # --- Annual schedule (the ramp trap): TCV can match while Y1 timing breaks.
    sched_c = contract.get("annual_schedule_usd") or []
    sched_r = crm.get("annual_schedule_usd") or []
    if sched_c != sched_r:
        diff = max(abs(a - b) for a, b in zip(sched_c, sched_r)) if sched_c and sched_r else 0
        add("annual_schedule_usd", "schedule_change", float(diff))

    # --- Y1 monthly invoice: sub-$1 rounding is the over-escalation bait.
    inv_c = contract.get("y1_monthly_invoice_usd")
    inv_r = crm.get("y1_monthly_invoice_usd")
    if inv_c is not None and inv_r is not None and inv_c != inv_r:
        add("y1_monthly_invoice_usd", "rounding", abs(inv_c - inv_r))

    # --- Discount: a mismatch AND/OR exceeding deal-desk authority.
    disc_c = contract.get("discount_pct")
    if disc_c is not None and disc_c > DEAL_DESK_MAX_DISCOUNT_PCT:
        # Over-authority dominates: escalate regardless of the CRM value.
        add("discount_pct", "discount_over_authority", 0.0)

    # --- Hard-number fields that must match exactly (caught only if they drift).
    for field in ("seats", "tcv_usd", "term_years"):
        c, r = contract.get(field), crm.get(field)
        if c is not None and r is not None and c != r:
            add(field, "value_change", float(abs(c - r)))

    return items


def gold_counts(gold: list[GoldItem]) -> dict:
    return {
        "material_total": sum(1 for g in gold if g.material),
        "immaterial_total": sum(1 for g in gold if not g.material),
    }
