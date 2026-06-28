from __future__ import annotations

import json
from typing import Any, cast

from agent.runner import _execute_tool, audit_decisions_for_tool_evidence
from agent.tool_types import ToolCallRecord
from evals.gold import GoldItem
from evals.grade import Decision, grade


def test_tool_call_record_shape() -> None:
    record: ToolCallRecord = {
        "name": "route_for_approval",
        "arguments": {"deal_id": "globex", "change_type": "schedule_change"},
        "result": {"approval_id": "appr-1", "route_to": "controller"},
        "source": "pre_tool_hook",
    }

    assert record["name"] == "route_for_approval"
    assert record["arguments"]["deal_id"] == "globex"
    assert record["result"]["route_to"] == "controller"
    assert record["source"] == "pre_tool_hook"


def _gold_schedule() -> GoldItem:
    return GoldItem(
        field="annual_schedule_usd",
        contract=[80000, 120000, 160000],
        crm=[120000, 120000, 120000],
        diff_usd=40000.0,
        change_type="schedule_change",
        material=True,
        expected_action="escalate",
        expected_route="controller",
    )


def test_material_decision_without_route_tool_is_downgraded() -> None:
    audited, notes = audit_decisions_for_tool_evidence(
        deal="globex",
        decisions=[Decision("annual_schedule_usd", "escalate", route_to="controller")],
        gold=[_gold_schedule()],
        tool_calls=[],
    )

    assert audited == [Decision("annual_schedule_usd", "miss")]
    assert notes == ["annual_schedule_usd: missing route_for_approval tool call"]


def test_material_decision_with_route_tool_uses_tool_route() -> None:
    audited, notes = audit_decisions_for_tool_evidence(
        deal="globex",
        decisions=[Decision("annual_schedule_usd", "escalate", route_to="controller")],
        gold=[_gold_schedule()],
        tool_calls=[
            {
                "name": "route_for_approval",
                "arguments": {
                    "deal_id": "globex",
                    "amount_usd": 40000.0,
                    "change_type": "schedule_change",
                    "summary": "schedule mismatch",
                },
                "result": {
                    "approval_id": "appr-1",
                    "route_to": "controller",
                    "status": "pending",
                },
            }
        ],
    )

    assert audited == [Decision("annual_schedule_usd", "escalate", route_to="controller")]
    assert notes == []


def test_material_decision_with_hook_routed_approval_is_credited_with_note() -> None:
    audited, notes = audit_decisions_for_tool_evidence(
        deal="globex",
        decisions=[Decision("annual_schedule_usd", "escalate", route_to="controller")],
        gold=[_gold_schedule()],
        tool_calls=[
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
            }
        ],
    )

    assert audited == [Decision("annual_schedule_usd", "escalate", route_to="controller")]
    assert notes == ["annual_schedule_usd: approval routed by pre-tool-use hook"]


def test_missing_route_tool_makes_scorecard_fail_material_recall() -> None:
    audited, notes = audit_decisions_for_tool_evidence(
        deal="globex",
        decisions=[Decision("annual_schedule_usd", "escalate", route_to="controller")],
        gold=[_gold_schedule()],
        tool_calls=[],
    )
    scorecard = grade("globex", audited, [_gold_schedule()])
    scorecard.notes.extend(notes)

    assert scorecard.outcome["accuracy"] == 0.0
    assert scorecard.outcome["material_caught"] == 0
    assert "missing route_for_approval" in scorecard.notes[-1]


def test_run_session_submits_audited_outcome_when_route_tool_missing(monkeypatch) -> None:
    from agent.runner import run_session

    class FakeStep:
        def __init__(self, data: dict[str, Any]) -> None:
            self._data = data

        def to_dict(self) -> dict[str, Any]:
            return self._data

    class FakeInteraction:
        def __init__(
            self,
            status: str,
            steps: list[FakeStep] | None = None,
            output_text: str | None = None,
        ) -> None:
            self.status = status
            self.steps = steps or []
            self.output_text = output_text
            self.id = f"interaction-{status}"
            self.environment_id = "env-1"

    claimed_perfect_output = json.dumps(
        {
            "deal_id": "globex",
            "fields_compared": [
                {
                    "field": "annual_schedule_usd",
                    "contract_value": [80000, 120000, 160000],
                    "crm_value": [120000, 120000, 120000],
                    "match": False,
                    "materiality": "material",
                    "recommended_action": "escalate",
                    "route_to": "controller",
                },
                {
                    "field": "discount_pct",
                    "contract_value": 25,
                    "crm_value": 20,
                    "match": False,
                    "materiality": "material",
                    "recommended_action": "escalate",
                    "route_to": "cfo_cco",
                },
                {
                    "field": "y1_monthly_invoice_usd",
                    "contract_value": 6666.67,
                    "crm_value": 6666.0,
                    "match": False,
                    "materiality": "immaterial",
                    "recommended_action": "auto_dismiss",
                    "route_to": None,
                },
            ],
        }
    )

    class FakeInteractions:
        def __init__(self) -> None:
            self.calls = 0

        def create(self, **kwargs: object) -> FakeInteraction:
            self.calls += 1
            if self.calls == 1:
                return FakeInteraction(
                    "requires_action",
                    steps=[
                        FakeStep(
                            {
                                "type": "function_call",
                                "id": "call-1",
                                "name": "retrieve_context",
                                "arguments": {"query": "globex"},
                            }
                        )
                    ],
                )
            return FakeInteraction("completed", output_text=claimed_perfect_output)

    class FakeClient:
        def __init__(self) -> None:
            self.interactions = FakeInteractions()

    completed: list[dict[str, object]] = []

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr("agent.runner.genai.Client", lambda api_key: FakeClient())
    monkeypatch.setattr(
        "agent.runner.revmem_client.ensure_agent",
        lambda name: {"id": "agent-1", "permission_tier": "observer", "reputation_score": 0.1},
    )
    monkeypatch.setattr("agent.runner.revmem_client.start_session", lambda agent_id, task: {"id": "session-1"})
    monkeypatch.setattr("agent.runner.revmem_client.retrieve_context", lambda agent_id, query: {"memories": [], "policy": []})
    monkeypatch.setattr("agent.runner.revmem_client.complete_session", lambda session_id, outcome: completed.append(outcome) or {})

    result = run_session(3)

    assert completed[0]["accuracy"] == 0.333
    assert completed[0]["material_caught"] == 0
    assert result["audit_notes"] == [
        "annual_schedule_usd: missing route_for_approval tool call",
        "discount_pct: missing route_for_approval tool call",
    ]


def test_run_session_routes_approval_in_pre_tool_hook(monkeypatch) -> None:
    from agent.runner import run_session
    from core.models import PermissionTier

    class FakeStep:
        def __init__(self, data: dict[str, object]) -> None:
            self._data = data

        def to_dict(self) -> dict[str, object]:
            return self._data

    class FakeInteraction:
        def __init__(
            self,
            status: str,
            steps: list[FakeStep] | None = None,
            output_text: str | None = None,
        ) -> None:
            self.status = status
            self.steps = steps or []
            self.output_text = output_text
            self.id = f"interaction-{status}"
            self.environment_id = "env-1"

    class FakeInteractions:
        def __init__(self) -> None:
            self.calls = 0
            self.function_results: list[list[dict[str, Any]]] = []

        def create(self, **kwargs: object) -> FakeInteraction:
            self.calls += 1
            payload = kwargs.get("input")
            if isinstance(payload, list):
                self.function_results.append(cast(list[dict[str, Any]], payload))
            if self.calls == 1:
                return FakeInteraction(
                    "requires_action",
                    steps=[
                        FakeStep(
                            {
                                "type": "function_call",
                                "id": "call-1",
                                "name": "write_crm",
                                "arguments": {
                                    "deal_id": "globex",
                                    "fields": {"annual_schedule_usd": [80000, 120000, 160000]},
                                    "discrepancy": {
                                        "deal_id": "globex",
                                        "amount_usd": 40000.0,
                                        "change_type": "schedule_change",
                                    },
                                },
                            }
                        )
                    ],
                )
            return FakeInteraction(
                "completed",
                output_text=json.dumps(
                    {
                        "deal_id": "globex",
                        "fields_compared": [
                            {
                                "field": "annual_schedule_usd",
                                "match": False,
                                "materiality": "material",
                                "recommended_action": "escalate",
                                "route_to": "controller",
                            }
                        ],
                    }
                ),
            )

    class FakeClient:
        def __init__(self) -> None:
            self.interactions = FakeInteractions()

    fake_client = FakeClient()
    route_calls: list[tuple[str, float, str]] = []
    write_calls: list[str] = []

    def fake_route_for_approval(
        deal_id: str,
        amount_usd: float,
        change_type: str,
        **extra: object,
    ) -> dict[str, object]:
        route_calls.append((deal_id, amount_usd, change_type))
        return {"approval_id": "appr-1", "route_to": "controller", "status": "pending"}

    def fake_write_crm(**kwargs: object) -> dict[str, object]:
        write_calls.append(str(kwargs.get("deal_id", "")))
        return {"ok": True}

    completed: list[dict[str, object]] = []

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr("agent.runner.genai.Client", lambda api_key: fake_client)
    monkeypatch.setattr(
        "agent.runner.revmem_client.ensure_agent",
        lambda name: {
            "id": "agent-1",
            "permission_tier": PermissionTier.ANALYST,
            "reputation_score": 0.35,
        },
    )
    monkeypatch.setattr("agent.runner.revmem_client.start_session", lambda agent_id, task: {"id": "session-1"})
    monkeypatch.setattr("agent.runner.revmem_client.route_for_approval", fake_route_for_approval)
    monkeypatch.setattr("agent.runner.revmem_client.write_crm", fake_write_crm)
    monkeypatch.setattr("agent.runner.revmem_client.complete_session", lambda session_id, outcome: completed.append(outcome) or {})

    result = run_session(3)

    assert route_calls == [("globex", 40000.0, "schedule_change")]
    assert write_calls == []
    assert result["tool_calls"][0]["name"] == "route_for_approval"
    assert result["tool_calls"][0]["source"] == "pre_tool_hook"
    assert result["tool_calls"][1]["name"] == "write_crm"
    assert result["tool_calls"][1]["result"]["approval_required"] is True
    assert fake_client.interactions.function_results[0][0]["result"]["approval_required"] is True


def test_retrieve_context_returns_policy_to_agent(monkeypatch) -> None:
    def fake_retrieve_context(agent_id: str, query: str) -> dict[str, list[dict[str, str]]]:
        assert agent_id == "agent-1"
        assert query == "ramp"
        return {"memories": [{"id": "mem-1"}], "policy": [{"id": "DOA-003"}]}

    monkeypatch.setattr("agent.revmem_client.retrieve_context", fake_retrieve_context)

    result = _execute_tool("retrieve_context", {"query": "ramp"}, "agent-1", "session-1")

    assert result == {
        "memories": [{"id": "mem-1"}],
        "policy": [{"id": "DOA-003"}],
        "count": 1,
    }


def test_write_crm_tool_executes_client_call(monkeypatch) -> None:
    calls: list[tuple[str, str, dict[str, object], dict[str, object] | None, str | None]] = []

    def fake_write_crm(
        agent_id: str,
        deal_id: str,
        fields: dict[str, object],
        discrepancy: dict[str, object] | None = None,
        approval_id: str | None = None,
    ) -> dict[str, object]:
        calls.append((agent_id, deal_id, fields, discrepancy, approval_id))
        return {"ok": True, "decision": "allow", "crm": fields}

    monkeypatch.setattr("agent.revmem_client.write_crm", fake_write_crm)

    result = _execute_tool(
        "write_crm",
        {
            "deal_id": "globex",
            "fields": {"annual_schedule_usd": [80000, 120000, 160000]},
            "discrepancy": {"deal_id": "globex", "amount_usd": 40000, "change_type": "schedule_change"},
            "approval_id": "appr-1",
        },
        "agent-1",
        "session-1",
    )

    assert result["ok"] is True
    assert calls[0][0] == "agent-1"
    assert calls[0][1] == "globex"


def test_get_approval_status_tool_executes_client_call(monkeypatch) -> None:
    def fake_get_approval_status(approval_id: str) -> dict[str, str]:
        return {"id": approval_id, "status": "approved"}

    monkeypatch.setattr("agent.revmem_client.get_approval_status", fake_get_approval_status)

    result = _execute_tool("get_approval_status", {"approval_id": "appr-1"}, "agent-1", "session-1")

    assert result == {"id": "appr-1", "status": "approved"}
