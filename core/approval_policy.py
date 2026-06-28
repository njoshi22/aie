from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from core.models import ApprovalStatus, PermissionTier


class ApprovalJoin:
    ANY = "any"
    ALL = "all"


@dataclass(frozen=True)
class ApprovalStep:
    step_id: str
    role: str
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True)
class MethodApprovalPlan:
    method: str
    required: bool
    allowed: bool = True
    join: str = ApprovalJoin.ALL
    steps: tuple[ApprovalStep, ...] = ()
    reason: str = ""


NO_APPROVAL_METHODS = {
    "agents.create",
    "sessions.create",
    "sessions.complete",
    "memory.create",
    "approval.route",
    "approval.decide",
    "approval.status",
}


def _crm_write_plan(context: Mapping[str, Any]) -> MethodApprovalPlan:
    tier = str(context.get("tier", ""))
    discrepancy = context.get("discrepancy", {})
    change_type = discrepancy.get("change_type") if isinstance(discrepancy, Mapping) else None

    if tier == PermissionTier.OBSERVER:
        return MethodApprovalPlan(
            "crm.write",
            required=False,
            allowed=False,
            reason="tier observer cannot write CRM",
        )
    if tier == PermissionTier.AUTONOMOUS and change_type != "discount_over_authority":
        return MethodApprovalPlan("crm.write", required=False, reason="policy-covered autonomous write")
    if change_type == "discount_over_authority":
        return MethodApprovalPlan(
            "crm.write",
            required=True,
            join=ApprovalJoin.ALL,
            steps=(
                ApprovalStep("cfo", "cfo"),
                ApprovalStep("cco", "cco", depends_on=("cfo",)),
            ),
            reason="discount over authority requires CFO then CCO approval",
        )
    return MethodApprovalPlan(
        "crm.write",
        required=True,
        join=ApprovalJoin.ALL,
        steps=(ApprovalStep("controller", "controller"),),
        reason="material CRM write requires controller approval",
    )


def _policy_update_plan(context: Mapping[str, Any]) -> MethodApprovalPlan:
    return MethodApprovalPlan(
        "policy.update",
        required=True,
        join=ApprovalJoin.ANY,
        steps=(
            ApprovalStep("finance_admin", "finance_admin"),
            ApprovalStep("controller", "controller"),
        ),
        reason="policy updates require finance admin or controller approval",
    )


def approval_plan_for_method(method: str, context: Mapping[str, Any]) -> MethodApprovalPlan:
    if method in NO_APPROVAL_METHODS:
        return MethodApprovalPlan(method, required=False, reason="method does not require approval")
    if method == "crm.write":
        return _crm_write_plan(context)
    if method == "policy.update":
        return _policy_update_plan(context)
    raise KeyError(f"no approval policy registered for method {method}")


def approval_request_satisfied(join: str, approvals: Sequence[Mapping[str, object]]) -> bool:
    statuses = [
        approval.get("status")
        for approval in approvals
        if approval.get("status") != ApprovalStatus.REROUTED
    ]
    if not statuses:
        return False
    if join == ApprovalJoin.ANY:
        return ApprovalStatus.APPROVED in statuses
    return all(status == ApprovalStatus.APPROVED for status in statuses)


def dependencies_satisfied(step_id: str, approvals: Sequence[Mapping[str, object]]) -> bool:
    dependencies: tuple[str, ...] = ()
    for approval in approvals:
        if approval.get("step_id") == step_id:
            raw = approval.get("depends_on", "")
            if isinstance(raw, str):
                dependencies = tuple(part for part in raw.split(",") if part)
            elif isinstance(raw, Sequence):
                dependencies = tuple(str(part) for part in raw)
            break
    by_step = {approval.get("step_id", ""): approval.get("status", "") for approval in approvals}
    return all(by_step.get(dep) == ApprovalStatus.APPROVED for dep in dependencies)
