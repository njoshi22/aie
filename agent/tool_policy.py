from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from agent.tool_types import JsonObject, JsonValue, ToolCallRecord
from core import governance


class ApprovalClient(Protocol):
    def route_for_approval(
        self,
        deal_id: str,
        amount_usd: float,
        change_type: str,
        **extra: object,
    ) -> JsonObject: ...

    def get_approval_status(self, approval_id: str) -> JsonObject: ...


@dataclass(frozen=True)
class ToolUseRequest:
    name: str
    arguments: JsonObject
    agent_id: str
    session_id: str
    tier: str


@dataclass(frozen=True)
class PreToolUseDecision:
    allow: bool
    result: JsonObject | None = None
    tool_records: tuple[ToolCallRecord, ...] = ()


def _object_arg(arguments: JsonObject, key: str) -> JsonObject:
    value = arguments.get(key)
    return value if isinstance(value, dict) else {}


def _string_arg(arguments: JsonObject, key: str) -> str:
    value = arguments.get(key)
    return value if isinstance(value, str) else ""


def _string_value(value: JsonValue, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _float_value(value: JsonValue, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    return default


def _route_summary(deal_id: str, amount_usd: float, change_type: str) -> str:
    return f"write_crm requested for {deal_id} {change_type} {amount_usd:.2f}"


def _deny(message: str) -> PreToolUseDecision:
    return PreToolUseDecision(
        allow=False,
        result={
            "error": message,
            "policy_decision": "deny",
            "skipped": True,
        },
    )


def _block_for_approval(approval_id: str, status: str) -> PreToolUseDecision:
    return PreToolUseDecision(
        allow=False,
        result={
            "error": f"write_crm blocked until approval {approval_id} is approved",
            "approval_required": True,
            "approval_id": approval_id,
            "approval_status": status,
            "policy_decision": "needs_approval",
            "skipped": True,
        },
    )


def _route_and_block(request: ToolUseRequest, approvals: ApprovalClient) -> PreToolUseDecision:
    discrepancy = _object_arg(request.arguments, "discrepancy")
    deal_id = _string_arg(request.arguments, "deal_id") or _string_value(discrepancy.get("deal_id", ""))
    amount_usd = _float_value(discrepancy.get("amount_usd", 0.0))
    change_type = _string_value(discrepancy.get("change_type", ""), "unknown")
    summary = _route_summary(deal_id, amount_usd, change_type)
    route_args: JsonObject = {
        "deal_id": deal_id,
        "amount_usd": amount_usd,
        "change_type": change_type,
        "summary": summary,
    }
    approval = approvals.route_for_approval(
        deal_id,
        amount_usd,
        change_type,
        summary=summary,
    )
    approval_id = str(approval.get("approval_id", ""))
    status = str(approval.get("status", "pending"))
    route_record: ToolCallRecord = {
        "name": "route_for_approval",
        "arguments": route_args,
        "result": approval,
        "source": "pre_tool_hook",
    }
    return PreToolUseDecision(
        allow=False,
        result={
            "error": f"write_crm blocked until approval {approval_id} is approved",
            "approval_required": True,
            "approval_id": approval_id,
            "approval_status": status,
            "route_to": str(approval.get("route_to", "")),
            "policy_decision": "needs_approval",
            "skipped": True,
        },
        tool_records=(route_record,),
    )


def before_tool_use(request: ToolUseRequest, approvals: ApprovalClient) -> PreToolUseDecision:
    if not governance.can_use(request.tier, request.name):
        return _deny(f"tier {request.tier} cannot use {request.name}")

    if request.name != "write_crm":
        return PreToolUseDecision(allow=True)

    discrepancy = _object_arg(request.arguments, "discrepancy")
    approval_id = _string_arg(request.arguments, "approval_id")
    if approval_id:
        approval_status = approvals.get_approval_status(approval_id)
        status = str(approval_status.get("status", "pending"))
        decision = governance.authorize_write(request.tier, discrepancy, status)
        if decision == governance.WriteDecision.ALLOW:
            return PreToolUseDecision(allow=True)
        return _block_for_approval(approval_id, status)

    decision = governance.authorize_write(request.tier, discrepancy)
    if decision == governance.WriteDecision.ALLOW:
        return PreToolUseDecision(allow=True)
    if decision == governance.WriteDecision.DENY:
        return _deny(f"write_crm not allowed for tier {request.tier}")
    return _route_and_block(request, approvals)
