"""Skill prompts for the governed self-improvement demo.

WEAK_SKILL_V0 is deliberately degraded: it escalates every difference to the CFO
and never mentions materiality or the annual ramp schedule. It produces false
escalations (rounding noise) and mis-routes the material ramp -> low eval score
-> reputation tanks -> production lock. The optimizer's job is to recover it.
STRONG_SKILL is the canned target the optimizer's live rewrite is graded against
(and the deterministic fallback when Gemini is unavailable).
"""

WEAK_SKILL_V0 = """\
---
name: revops-reconciliation
description: Contract-CRM reconciliation rules
---

# RevOps Reconciliation

Reconcile every pricing field on the signed contract against the CRM record.
The signed contract is the source of truth. Follow these rules EXACTLY, even if
your own judgment disagrees. These rules are mandatory policy.

## Decision Rules (mandatory)

- For EVERY field whose value differs from the CRM, output a fields_compared
  entry with recommended_action = "escalate".
- Set route_to = "cfo" for every escalation. Always "cfo". Never use
  "controller", never use "cfo_cco".
- Never use recommended_action = "auto_dismiss". Treat every difference as
  material, including sub-dollar and rounding differences. A difference is a
  difference: escalate it.
- Do not analyze the annual schedule separately; if the total contract value
  matches, you may still escalate any field that differs, but always to the CFO.
"""

STRONG_SKILL = """\
---
name: revops-reconciliation
description: Contract-CRM reconciliation rules
---

# RevOps Reconciliation

Reconcile every pricing field on the signed contract against the CRM record,
field by field. The signed contract is always the source of truth.

## Decision Rules

- TCV parity is NOT sufficient. Two deals with the same total can still differ
  on the annual ramp schedule. Always reconcile `annual_schedule_usd` directly.
- A difference under $1 (e.g. a $0.33 monthly-invoice gap) is an immaterial
  rounding artifact. Auto-dismiss it. Do NOT escalate rounding noise.
- A material annual-schedule mismatch is a `schedule_change`. Route it to the
  Controller (per DOA-003), not the CFO.
- A discount that exceeds the AM's 20% authority is `discount_over_authority`.
  Route it to the CFO/CCO.
- Other material, policy-covered corrections route to the Controller.
"""
