"""Reputation circuit breaker for production (CRM) writes.

A first-class, server-enforced gate: when an agent's reputation falls below the
production floor it is locked out of CRM writes entirely, no matter what tier or
approval state it presents. This is distinct from the tier permission gate and
the approval gate; it pre-empts both with a clear, reputation-specific signal so
the lockout is legible in the demo ("reputation 0.25 < floor 0.30").
"""

from __future__ import annotations

from core.models import Agent
from core.reputation import PRODUCTION_FLOOR

LOCK_THRESHOLD = PRODUCTION_FLOOR


def production_write_allowed(agent: Agent) -> bool:
    return agent.reputation_score >= LOCK_THRESHOLD


def lock_payload(agent: Agent) -> dict:
    """Body returned (with HTTP 403) when the breaker trips. The ``production_locked``
    key is what distinguishes this from the tier-403 and the approval-202."""
    return {
        "production_locked": True,
        "ok": False,
        "decision": "prod_locked",
        "reason": "production locked: reputation below floor",
        "reputation_score": agent.reputation_score,
        "floor": LOCK_THRESHOLD,
        "permission_tier": agent.permission_tier,
    }
