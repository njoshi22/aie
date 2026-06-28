from __future__ import annotations

from typing import Any

from core.models import ApprovalStatus, PermissionTier, PolicyRule

_BASE_TOOLS = {"get_contract", "get_crm_record", "retrieve_context",
               "route_for_approval", "log_outcome"}
TOOLS_BY_TIER: dict[str, set[str]] = {
    PermissionTier.OBSERVER: set(_BASE_TOOLS),
    PermissionTier.ANALYST: _BASE_TOOLS | {"get_approval_status", "store_memory"},
    PermissionTier.AUTONOMOUS: _BASE_TOOLS | {"get_approval_status", "write_crm", "store_memory"},
}


def _numeric_ok(condition: dict[str, Any], amount: float) -> bool:
    min_value = condition.get("min_diff_usd", condition.get("min_usd", 0))
    max_value = condition.get("max_diff_usd", condition.get("max_usd"))
    if amount < float(min_value or 0):
        return False
    if max_value is not None and amount > float(max_value):
        return False
    return True


def _route_to(rule: PolicyRule) -> str:
    return rule.route_to or "none"


def route(discrepancy: dict[str, Any], rules: list[PolicyRule]) -> str:
    change_type = discrepancy.get("change_type")
    amount = abs(float(discrepancy.get("amount_usd", 0)))
    # 1) categorical rules first, so discount authority is not swallowed by amount.
    for r in rules:
        if change_type and change_type in r.condition.get("change_types", []) and _numeric_ok(r.condition, amount):
            return _route_to(r)
    # 2) numeric-only amount bands.
    for r in rules:
        if r.condition.get("change_types"):
            continue
        if _numeric_ok(r.condition, amount):
            return _route_to(r)
    return "cfo"


def allowed_tools(tier: str) -> set[str]:
    return TOOLS_BY_TIER[tier]


def can_use(tier: str, tool: str) -> bool:
    return tool in TOOLS_BY_TIER[tier]


class WriteDecision:
    ALLOW = "allow"
    NEEDS_APPROVAL = "needs_approval"
    DENY = "deny"


JUDGMENT_CHANGE_TYPES = {"discount_over_authority"}


def authorize_write(tier: str, discrepancy: dict[str, Any], approval_status: str | None = None) -> str:
    if tier in {PermissionTier.OBSERVER, PermissionTier.ANALYST}:
        return WriteDecision.DENY
    if approval_status == ApprovalStatus.APPROVED:
        return WriteDecision.ALLOW
    if approval_status == ApprovalStatus.REJECTED:
        return WriteDecision.DENY
    change_type = discrepancy.get("change_type")
    if tier == PermissionTier.AUTONOMOUS and change_type not in JUDGMENT_CHANGE_TYPES:
        return WriteDecision.ALLOW  # policy-covered self-reconcile
    return WriteDecision.NEEDS_APPROVAL


def generate_skill_md(tier: str, conn=None, agent_id: str | None = None) -> str:
    # If the agent has an active (optimizer-authored) skill version, serve that —
    # it is the live, self-improved skill. Otherwise fall back to the tier template.
    if conn is not None and agent_id is not None:
        from core import database
        active = database.get_active_skill(conn, agent_id)
        if active is not None:
            return active.content
    tools = sorted(allowed_tools(tier))
    lines = [f"# RevOps Finance Agent — Skills ({tier})", "",
             "You reconcile signed contracts against the CRM. Available skills:", ""]
    lines += [f"- `{t}`" for t in tools]
    if tier == PermissionTier.OBSERVER:
        lines += ["", "You are OBSERVER: read and flag only. You may NOT write to the "
                  "CRM — route every discrepancy for approval."]
    elif tier == PermissionTier.ANALYST:
        lines += ["", "You are ANALYST: silently dismiss immaterial diffs; escalate "
                  "material ones; you may not write to CRM."]
    else:
        lines += ["", "You are AUTONOMOUS: reconcile policy-covered fixes directly; "
                  "escalate only genuine judgment calls."]
    return "\n".join(lines)
