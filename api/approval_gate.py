from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from core import approval_policy, database
from core.models import Approval, ApprovalStatus


@dataclass(frozen=True)
class ApprovalGateResult:
    allowed: bool
    payload: dict[str, Any]


def _json_object(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): item for key, item in value.items()}


def _deal_id(context: Mapping[str, Any], discrepancy: Mapping[str, Any]) -> str:
    return str(context.get("deal_id") or discrepancy.get("deal_id") or "")


def _approval_rows(approvals: list[Approval]) -> list[dict[str, object]]:
    return [
        {
            "step_id": approval.step_id,
            "status": approval.status,
            "depends_on": approval.depends_on,
        }
        for approval in approvals
    ]


def _aggregate_status(approvals: list[Approval]) -> str:
    rows = _approval_rows(approvals)
    if any(approval.status == ApprovalStatus.REJECTED for approval in approvals):
        return ApprovalStatus.REJECTED
    if approvals and approval_policy.approval_request_satisfied(approvals[0].join, rows):
        return ApprovalStatus.APPROVED
    return ApprovalStatus.PENDING


def approval_request_payload(approvals: list[Approval], reason: str) -> dict[str, Any]:
    request_id = approvals[0].request_id if approvals else ""
    join = approvals[0].join if approvals else approval_policy.ApprovalJoin.ALL
    return {
        "ok": False,
        "decision": "needs_approval",
        "approval_required": True,
        "approval_id": approvals[0].id if approvals else "",
        "approval_request_id": request_id,
        "approval_join": join,
        "approval_status": _aggregate_status(approvals),
        "reason": reason,
        "approvals": [
            {
                "approval_id": approval.id,
                "step_id": approval.step_id,
                "role": approval.approver_role,
                "status": approval.status,
                "depends_on": approval.depends_on,
            }
            for approval in approvals
        ],
    }


def _approval_request_rows(
    method: str,
    plan: approval_policy.MethodApprovalPlan,
    context: Mapping[str, Any],
) -> list[Approval]:
    request_id = str(uuid.uuid4())
    discrepancy = _json_object(context.get("discrepancy", {}))
    deal_id = _deal_id(context, discrepancy)
    return [
        Approval(
            request_id=request_id,
            method=method,
            join=plan.join,
            step_id=step.step_id,
            depends_on=list(step.depends_on),
            deal_id=deal_id,
            discrepancy=discrepancy,
            approver_role=step.role,
        )
        for step in plan.steps
    ]


def _request_matches_context(
    approvals: list[Approval],
    method: str,
    context: Mapping[str, Any],
) -> bool:
    discrepancy = _json_object(context.get("discrepancy", {}))
    deal_id = _deal_id(context, discrepancy)
    for approval in approvals:
        if approval.method != method:
            return False
        if deal_id and approval.deal_id != deal_id:
            return False
        if discrepancy and approval.discrepancy != discrepancy:
            return False
    return True


def _allowed_payload(request_id: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": True,
        "decision": "allow",
        "approval_required": False,
    }
    if request_id:
        payload["approval_request_id"] = request_id
    return payload


def _denied_payload(reason: str) -> dict[str, Any]:
    return {
        "ok": False,
        "decision": "deny",
        "approval_required": False,
        "reason": reason,
    }


def ensure_method_approved(
    conn: sqlite3.Connection,
    method: str,
    context: Mapping[str, Any],
    request_id: str | None = None,
) -> ApprovalGateResult:
    plan = approval_policy.approval_plan_for_method(method, context)
    if not plan.allowed:
        return ApprovalGateResult(False, _denied_payload(plan.reason))
    if not plan.required:
        return ApprovalGateResult(True, _allowed_payload(request_id))

    if request_id:
        approvals = database.list_approvals_for_request(conn, request_id)
        if not approvals:
            return ApprovalGateResult(False, _denied_payload("approval request not found"))
        if not _request_matches_context(approvals, method, context):
            return ApprovalGateResult(False, _denied_payload("approval request does not match method context"))

        payload = approval_request_payload(approvals, plan.reason)
        if approval_policy.approval_request_satisfied(approvals[0].join, _approval_rows(approvals)):
            return ApprovalGateResult(True, _allowed_payload(request_id))
        return ApprovalGateResult(False, payload)

    approvals = _approval_request_rows(method, plan, context)
    database.insert_approvals(conn, approvals)
    return ApprovalGateResult(False, approval_request_payload(approvals, plan.reason))
