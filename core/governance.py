from __future__ import annotations

from typing import Any

from core.models import ApprovalStatus, PermissionTier, PolicyRule

_BASE_TOOLS = {"get_contract", "get_crm_record", "retrieve_context",
               "route_for_approval", "log_outcome"}
TOOLS_BY_TIER: dict[str, set[str]] = {
    PermissionTier.OBSERVER: set(_BASE_TOOLS),
    PermissionTier.ANALYST: _BASE_TOOLS | {"write_crm", "store_memory"},
    PermissionTier.AUTONOMOUS: _BASE_TOOLS | {"write_crm", "store_memory"},
}


def route(discrepancy: dict[str, Any], rules: list[PolicyRule]) -> str:
    change_type = discrepancy.get("change_type")
    amount = abs(float(discrepancy.get("amount_usd", 0)))
    # 1) change-type overrides (material structural changes ignore amount)
    for r in rules:
        if change_type and change_type in r.condition.get("change_types", []):
            return r.route_to
    # 2) amount bands (rules without change_types)
    for r in rules:
        cond = r.condition
        if cond.get("change_types"):
            continue
        lo = float(cond.get("min_usd", 0))
        hi = cond.get("max_usd")
        if amount >= lo and (hi is None or amount < float(hi)):
            return r.route_to
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
    if tier == PermissionTier.OBSERVER:
        return WriteDecision.DENY
    if approval_status == ApprovalStatus.APPROVED:
        return WriteDecision.ALLOW
    if approval_status == ApprovalStatus.REJECTED:
        return WriteDecision.DENY
    change_type = discrepancy.get("change_type")
    if tier == PermissionTier.AUTONOMOUS and change_type not in JUDGMENT_CHANGE_TYPES:
        return WriteDecision.ALLOW  # policy-covered self-reconcile
    return WriteDecision.NEEDS_APPROVAL


def generate_skill_md(tier: str) -> str:
    tools = sorted(allowed_tools(tier))
    lines = [f"# RevOps Finance Agent — Skills ({tier})", "",
             "You reconcile signed contracts against the CRM. Available skills:", ""]
    lines += [f"- `{t}`" for t in tools]
    if tier == PermissionTier.OBSERVER:
        lines += ["", "You are OBSERVER: read and flag only. You may NOT write to the "
                  "CRM — route every discrepancy for approval."]
    elif tier == PermissionTier.ANALYST:
        lines += ["", "You are ANALYST: silently dismiss immaterial diffs; escalate "
                  "material ones; on approval you may `write_crm`."]
    else:
        lines += ["", "You are AUTONOMOUS: reconcile policy-covered fixes directly; "
                  "escalate only genuine judgment calls."]
    return "\n".join(lines)
