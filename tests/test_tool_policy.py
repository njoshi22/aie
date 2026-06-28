from __future__ import annotations

from agent.tool_policy import ToolUseRequest, before_tool_use
from agent.tool_types import JsonObject
from core.models import ApprovalStatus, PermissionTier


class FakeApprovals:
    def __init__(self, status: str = ApprovalStatus.PENDING) -> None:
        self.status = status
        self.route_calls: list[tuple[str, float, str, JsonObject]] = []
        self.status_calls: list[str] = []

    def route_for_approval(
        self,
        deal_id: str,
        amount_usd: float,
        change_type: str,
        **extra: object,
    ) -> JsonObject:
        payload: JsonObject = {
            "approval_id": "appr-1",
            "route_to": "controller",
            "status": "pending",
        }
        self.route_calls.append((
            deal_id,
            amount_usd,
            change_type,
            {"summary": str(extra.get("summary", ""))},
        ))
        return payload

    def get_approval_status(self, approval_id: str) -> JsonObject:
        self.status_calls.append(approval_id)
        return {"id": approval_id, "status": self.status}


def _write_request(
    tier: str,
    approval_id: str | None = None,
    change_type: str = "schedule_change",
) -> ToolUseRequest:
    args: JsonObject = {
        "deal_id": "globex",
        "fields": {"annual_schedule_usd": [80000, 120000, 160000]},
        "discrepancy": {
            "deal_id": "globex",
            "amount_usd": 40000.0,
            "change_type": change_type,
        },
    }
    if approval_id is not None:
        args["approval_id"] = approval_id
    return ToolUseRequest(
        name="write_crm",
        arguments=args,
        agent_id="agent-1",
        session_id="session-1",
        tier=tier,
    )


def test_hook_allows_observer_read_tool() -> None:
    decision = before_tool_use(
        ToolUseRequest(
            name="retrieve_context",
            arguments={"query": "globex ramp"},
            agent_id="agent-1",
            session_id="session-1",
            tier=PermissionTier.OBSERVER,
        ),
        FakeApprovals(),
    )

    assert decision.allow is True
    assert decision.result is None
    assert decision.tool_records == ()


def test_hook_allows_analyst_approval_status_tool() -> None:
    decision = before_tool_use(
        ToolUseRequest(
            name="get_approval_status",
            arguments={"approval_id": "appr-1"},
            agent_id="agent-1",
            session_id="session-1",
            tier=PermissionTier.ANALYST,
        ),
        FakeApprovals(),
    )

    assert decision.allow is True
    assert decision.result is None
    assert decision.tool_records == ()


def test_hook_denies_tool_not_allowed_for_tier() -> None:
    approvals = FakeApprovals()

    decision = before_tool_use(_write_request(PermissionTier.OBSERVER), approvals)

    assert decision.allow is False
    assert decision.result == {
        "error": "tier observer cannot use write_crm",
        "policy_decision": "deny",
        "skipped": True,
    }
    assert approvals.route_calls == []


def test_hook_routes_analyst_write_before_execution() -> None:
    approvals = FakeApprovals()

    decision = before_tool_use(_write_request(PermissionTier.ANALYST), approvals)

    assert decision.allow is False
    assert decision.result is not None
    assert decision.result["approval_required"] is True
    assert decision.result["approval_id"] == "appr-1"
    assert approvals.route_calls == [
        (
            "globex",
            40000.0,
            "schedule_change",
            {"summary": "write_crm requested for globex schedule_change 40000.00"},
        )
    ]
    assert decision.tool_records == (
        {
            "name": "route_for_approval",
            "arguments": {
                "deal_id": "globex",
                "amount_usd": 40000.0,
                "change_type": "schedule_change",
                "summary": "write_crm requested for globex schedule_change 40000.00",
            },
            "result": {
                "approval_id": "appr-1",
                "route_to": "controller",
                "status": "pending",
            },
            "source": "pre_tool_hook",
        },
    )


def test_hook_allows_write_with_approved_approval_id() -> None:
    approvals = FakeApprovals(status=ApprovalStatus.APPROVED)

    decision = before_tool_use(_write_request(PermissionTier.ANALYST, approval_id="appr-1"), approvals)

    assert decision.allow is True
    assert decision.result is None
    assert approvals.status_calls == ["appr-1"]


def test_hook_blocks_write_with_pending_approval_id() -> None:
    approvals = FakeApprovals(status=ApprovalStatus.PENDING)

    decision = before_tool_use(_write_request(PermissionTier.ANALYST, approval_id="appr-1"), approvals)

    assert decision.allow is False
    assert decision.result == {
        "error": "write_crm blocked until approval appr-1 is approved",
        "approval_required": True,
        "approval_id": "appr-1",
        "approval_status": "pending",
        "policy_decision": "needs_approval",
        "skipped": True,
    }
