from __future__ import annotations

import json
from typing import Any, cast

from agent import runner
from agent.prompts import build_reconciliation_prompt
from agent.scenarios import SCENARIOS
from agent.tool_types import JsonObject, ToolCallRecord
from evals.gold import GoldItem
from evals.grade import Decision, grade


def test_tool_call_record_shape() -> None:
    record: ToolCallRecord = {
        "name": "route_for_approval",
        "arguments": {"deal_id": "globex", "change_type": "schedule_change"},
        "result": {"approval_request_id": "req-1", "route_to": "controller"},
        "source": "model",
    }

    assert record["name"] == "route_for_approval"
    assert record["arguments"]["deal_id"] == "globex"
    assert record["result"]["route_to"] == "controller"
    assert record["source"] == "model"


class _FakeInteractions:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(kwargs)
        return {"ok": True}


class _FakeClient:
    def __init__(self) -> None:
        self.interactions = _FakeInteractions()


class _TimingListener:
    def __init__(self) -> None:
        self.events: list[tuple[str, str] | tuple[str, str, float]] = []

    def on_session_start(self, session_number: int, deal: str, tier: str, reputation: float, task: str) -> None:
        pass

    def on_tool_call(self, name: str, arguments: JsonObject) -> None:
        pass

    def on_tool_result(self, name: str, result: JsonObject) -> None:
        pass

    def on_memory_retrieved(self, memories: list[JsonObject]) -> None:
        pass

    def on_agent_response(self, text: str) -> None:
        pass

    def on_approval_needed(self, approval: JsonObject) -> None:
        pass

    def on_graded(self, scorecard: object, graded_from_output: bool) -> None:
        pass

    def on_session_end(self, result: JsonObject) -> None:
        pass

    def on_agent_api_start(self, label: str) -> None:
        self.events.append(("start", label))

    def on_agent_api_end(self, label: str, elapsed_s: float) -> None:
        self.events.append(("end", label, elapsed_s))

    def on_tool_timing(self, name: str, elapsed_s: float) -> None:
        pass


def test_interaction_create_reports_wait_timing() -> None:
    client = _FakeClient()
    listener = _TimingListener()

    result = runner._create_interaction(
        client,
        {"agent": "model", "input": "prompt"},
        "initial response",
        listener,
        debug=False,
    )

    assert result == {"ok": True}
    assert client.interactions.calls == [
        {"background": True, "timeout": runner.AGENT_API_TIMEOUT_S, "agent": "model", "input": "prompt"}
    ]
    assert listener.events[0] == ("start", "initial response")
    end_event = listener.events[1]
    assert end_event[0:2] == ("end", "initial response")
    assert len(end_event) == 3
    assert end_event[2] >= 0


def test_create_interaction_polls_background_until_terminal(monkeypatch) -> None:
    """Background create returns in_progress; _create_interaction must poll get() until terminal."""
    class FakeInteraction:
        def __init__(self, status: str) -> None:
            self.status = status
            self.id = "v1_interaction"

    class FakeInteractions:
        def __init__(self) -> None:
            self.created_background: bool | None = None
            self.get_calls = 0

        def create(self, **kwargs: object) -> FakeInteraction:
            self.created_background = bool(kwargs.get("background"))
            return FakeInteraction("in_progress")

        def get(self, id: str, **kwargs: object) -> FakeInteraction:
            self.get_calls += 1
            return FakeInteraction("requires_action" if self.get_calls >= 2 else "in_progress")

    class FakeClient:
        def __init__(self) -> None:
            self.interactions = FakeInteractions()

    monkeypatch.setattr("agent.runner.time.sleep", lambda _s: None)
    client = FakeClient()

    result = runner._create_interaction(client, {"agent": "m", "input": "p"}, "lbl", _TimingListener(), debug=False)

    assert client.interactions.created_background is True
    assert client.interactions.get_calls == 2  # polled until it left in_progress
    assert result.status == "requires_action"


def test_session_one_completion_payload_has_no_hardcoded_lesson() -> None:
    payload = runner._completion_payload(
        {"accuracy": 0.0},
        memories_used=[],
        memories_created=[],
        scenario=cast(runner.Scenario, SCENARIOS[1]),
    )

    assert "lesson" not in payload


def test_prompt_directs_service_layer_tool_use_without_inline_data() -> None:
    prompt = build_reconciliation_prompt(
        "acme",
        {"get_contract", "get_crm_record", "retrieve_context", "route_for_approval"},
    )

    # No data is embedded — the agent must fetch via tools.
    assert "No data is included in this prompt" in prompt
    assert "get_contract" in prompt and "get_crm_record" in prompt
    assert "retrieve_context first" in prompt
    # Observer escalates via route_for_approval and may not write CRM.
    assert "route_for_approval" in prompt
    assert "may NOT write to CRM" in prompt
    assert "write_crm" not in prompt
    # Output contract points at AGENTS.md schema.
    assert "fields_compared schema" in prompt


def test_prompt_analyst_uses_write_crm() -> None:
    prompt = build_reconciliation_prompt(
        "globex",
        {"get_contract", "get_crm_record", "retrieve_context", "write_crm", "get_approval_status"},
    )
    assert "write_crm" in prompt
    assert "get_approval_status" in prompt


def test_run_session_uses_service_allowed_tools_and_skill_md(monkeypatch) -> None:
    class FakeInteraction:
        status = "completed"
        output_text = "{}"
        id = "interaction-completed"
        environment_id = "env-1"
        steps: list[object] = []

    class FakeInteractions:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def create(self, **kwargs: object) -> FakeInteraction:
            self.calls.append(kwargs)
            return FakeInteraction()

    class FakeClient:
        def __init__(self) -> None:
            self.interactions = FakeInteractions()

    fake_client = FakeClient()
    completed: list[dict[str, object]] = []

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr("agent.runner.genai.Client", lambda api_key: fake_client)
    monkeypatch.setattr(
        "agent.runner.revmem_client.ensure_agent",
        lambda name: {
            "id": "agent-1",
            "permission_tier": "observer",
            "reputation_score": 0.1,
            "allowed_tools": ["route_for_approval", "get_contract", "log_outcome"],
        },
    )
    monkeypatch.setattr("agent.runner.revmem_client.get_skill_md", lambda agent_id: f"# service skill for {agent_id}")
    monkeypatch.setattr("agent.runner.revmem_client.start_session", lambda agent_id, task: {"id": "session-1"})
    monkeypatch.setattr("agent.runner.revmem_client.complete_session", lambda session_id, outcome: completed.append(outcome) or {})

    runner.run_session(3)

    initial_call = fake_client.interactions.calls[0]
    assert [tool["name"] for tool in cast(list[dict[str, object]], initial_call["tools"])] == [
        "get_contract",
        "route_for_approval",
    ]
    environment = cast(dict[str, object], initial_call["environment"])
    sources = cast(list[dict[str, str]], environment["sources"])
    skill_sources = [source for source in sources if source["target"].endswith("SKILL.md")]
    assert skill_sources == [
        {
            "type": "inline",
            "target": ".agents/skills/reconciliation/SKILL.md",
            "content": "# service skill for agent-1",
        }
    ]
    assert "write_crm" not in str(initial_call["input"])


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
    audited, notes = runner.audit_decisions_for_tool_evidence(
        deal="globex",
        decisions=[Decision("annual_schedule_usd", "escalate", route_to="controller")],
        gold=[_gold_schedule()],
        tool_calls=[],
    )

    assert audited == [Decision("annual_schedule_usd", "miss")]
    assert notes == ["annual_schedule_usd: missing approval request"]


def test_material_decision_with_route_tool_uses_tool_route() -> None:
    audited, notes = runner.audit_decisions_for_tool_evidence(
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


def test_material_decision_with_service_approval_request_is_credited() -> None:
    audited, notes = runner.audit_decisions_for_tool_evidence(
        deal="globex",
        decisions=[Decision("annual_schedule_usd", "escalate", route_to="controller")],
        gold=[_gold_schedule()],
        tool_calls=[
            {
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
                "result": {
                    "approval_required": True,
                    "approval_request_id": "req-1",
                    "approval_status": "pending",
                    "approvals": [
                        {
                            "approval_id": "appr-1",
                            "step_id": "controller",
                            "role": "controller",
                            "status": "pending",
                            "depends_on": [],
                        }
                    ],
                },
                "source": "model",
            }
        ],
    )

    assert audited == [Decision("annual_schedule_usd", "escalate", route_to="controller")]
    assert notes == []


def test_missing_route_tool_makes_scorecard_fail_material_recall() -> None:
    audited, notes = runner.audit_decisions_for_tool_evidence(
        deal="globex",
        decisions=[Decision("annual_schedule_usd", "escalate", route_to="controller")],
        gold=[_gold_schedule()],
        tool_calls=[],
    )
    scorecard = grade("globex", audited, [_gold_schedule()])
    scorecard.notes.extend(notes)

    assert scorecard.outcome["accuracy"] == 0.0
    assert scorecard.outcome["material_caught"] == 0
    assert "missing approval request" in scorecard.notes[-1]


def test_run_session_submits_audited_outcome_when_route_tool_missing(monkeypatch) -> None:
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
    route_calls: list[dict[str, object]] = []

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr("agent.runner.genai.Client", lambda api_key: FakeClient())
    monkeypatch.setattr(
        "agent.runner.revmem_client.ensure_agent",
        lambda name: {
            "id": "agent-1",
            "permission_tier": "observer",
            "reputation_score": 0.1,
            "allowed_tools": ["get_contract", "get_crm_record", "retrieve_context", "route_for_approval"],
        },
    )
    monkeypatch.setattr("agent.runner.revmem_client.start_session", lambda agent_id, task: {"id": "session-1"})
    monkeypatch.setattr("agent.runner.revmem_client.retrieve_context", lambda agent_id, query: {"memories": [], "policy": []})
    monkeypatch.setattr(
        "agent.runner.revmem_client.route_for_approval",
        lambda *args, **kwargs: route_calls.append({"args": args, "kwargs": kwargs}) or {"approval_id": "appr-unexpected"},
    )
    monkeypatch.setattr("agent.runner.revmem_client.complete_session", lambda session_id, outcome: completed.append(outcome) or {})

    result = runner.run_session(3)

    assert completed[0]["accuracy"] == 0.333
    assert completed[0]["material_caught"] == 0
    assert result["audit_notes"] == [
        "annual_schedule_usd: missing approval request",
        "discount_pct: missing approval request",
    ]
    assert route_calls == []


def test_run_session_records_service_method_approval_request(monkeypatch) -> None:
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
    write_calls: list[str] = []

    def fake_write_crm(**kwargs: object) -> dict[str, object]:
        write_calls.append(str(kwargs.get("deal_id", "")))
        return {
            "ok": False,
            "decision": "needs_approval",
            "approval_required": True,
            "approval_request_id": "req-1",
            "approval_join": "all",
            "approval_status": "pending",
            "approvals": [
                {
                    "approval_id": "appr-1",
                    "step_id": "controller",
                    "role": "controller",
                    "status": "pending",
                    "depends_on": [],
                }
            ],
        }

    completed: list[dict[str, object]] = []

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr("agent.runner.genai.Client", lambda api_key: fake_client)
    monkeypatch.setattr(
        "agent.runner.revmem_client.ensure_agent",
        lambda name: {
            "id": "agent-1",
            "permission_tier": PermissionTier.ANALYST,
            "reputation_score": 0.35,
            "allowed_tools": [
                "get_contract",
                "get_crm_record",
                "retrieve_context",
                "route_for_approval",
                "get_approval_status",
                "write_crm",
                "store_memory",
            ],
        },
    )
    monkeypatch.setattr("agent.runner.revmem_client.start_session", lambda agent_id, task: {"id": "session-1"})
    monkeypatch.setattr("agent.runner.revmem_client.retrieve_context", lambda agent_id, query: {"memories": [], "policy": []})
    monkeypatch.setattr("agent.runner.revmem_client.write_crm", fake_write_crm)
    monkeypatch.setattr("agent.runner.revmem_client.complete_session", lambda session_id, outcome: completed.append(outcome) or {})

    result = runner.run_session(3)

    assert write_calls == ["globex"]
    assert result["tool_calls"][0]["name"] == "write_crm"
    assert result["tool_calls"][0]["source"] == "model"
    assert result["tool_calls"][0]["result"]["approval_required"] is True
    assert result["approvals_routed"][0]["approval_request_id"] == "req-1"
    assert fake_client.interactions.function_results[0][0]["result"]["approval_required"] is True


def test_run_session_executes_repeated_tool_name_across_rounds(monkeypatch) -> None:
    """Regression: tool-result dedup must key on call_id, not tool name.

    interaction.steps is cumulative across the chain. A later round can issue a
    fresh function_call to the same tool name with a new call_id; deduping by name
    would treat it as already-resolved and silently drop it, stalling the loop.
    """
    class FakeStep:
        def __init__(self, data: dict[str, Any]) -> None:
            self._data = data

        def to_dict(self) -> dict[str, Any]:
            return self._data

    class FakeInteraction:
        def __init__(self, status: str, steps: list[FakeStep] | None = None, output_text: str | None = None) -> None:
            self.status = status
            self.steps = steps or []
            self.output_text = output_text
            self.id = f"interaction-{status}"
            self.environment_id = "env-1"

    fc_one = {"type": "function_call", "id": "call-1", "name": "retrieve_context", "arguments": {"query": "ramp"}}
    fr_one = {"type": "function_result", "call_id": "call-1", "name": "retrieve_context", "result": {}}
    fc_two = {"type": "function_call", "id": "call-2", "name": "retrieve_context", "arguments": {"query": "rounding"}}

    class FakeInteractions:
        def __init__(self) -> None:
            self.calls = 0
            self.submitted_call_ids: list[list[str]] = []

        def create(self, **kwargs: object) -> FakeInteraction:
            self.calls += 1
            payload = kwargs.get("input")
            if isinstance(payload, list):
                self.submitted_call_ids.append([cast(dict[str, Any], r)["call_id"] for r in payload])
            if self.calls == 1:
                return FakeInteraction("requires_action", steps=[FakeStep(fc_one)])
            if self.calls == 2:
                # Cumulative chain: call-1 resolved; a NEW same-name call-2 is pending.
                return FakeInteraction("requires_action", steps=[FakeStep(fc_one), FakeStep(fr_one), FakeStep(fc_two)])
            return FakeInteraction("completed", output_text="{}")

    class FakeClient:
        def __init__(self) -> None:
            self.interactions = FakeInteractions()

    fake_client = FakeClient()

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr("agent.runner.genai.Client", lambda api_key: fake_client)
    monkeypatch.setattr(
        "agent.runner.revmem_client.ensure_agent",
        lambda name: {
            "id": "agent-1",
            "permission_tier": "observer",
            "reputation_score": 0.1,
            "allowed_tools": ["get_contract", "get_crm_record", "retrieve_context", "route_for_approval"],
        },
    )
    monkeypatch.setattr("agent.runner.revmem_client.start_session", lambda agent_id, task: {"id": "session-1"})
    monkeypatch.setattr("agent.runner.revmem_client.retrieve_context", lambda agent_id, query: {"memories": [], "policy": []})
    monkeypatch.setattr("agent.runner.revmem_client.complete_session", lambda session_id, outcome: {})

    runner.run_session(3)

    # Both rounds ran: call-1, then the same-named call-2 (name-based dedup would have dropped call-2).
    assert fake_client.interactions.submitted_call_ids == [["call-1"], ["call-2"]]


def test_retrieve_context_returns_policy_to_agent(monkeypatch) -> None:
    def fake_retrieve_context(agent_id: str, query: str) -> dict[str, list[dict[str, str]]]:
        assert agent_id == "agent-1"
        assert query == "ramp"
        return {"memories": [{"id": "mem-1"}], "policy": [{"id": "DOA-003"}]}

    monkeypatch.setattr("agent.revmem_client.retrieve_context", fake_retrieve_context)

    result = runner._execute_tool("retrieve_context", {"query": "ramp"}, "agent-1", "session-1")

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
        approval_request_id: str | None = None,
    ) -> dict[str, object]:
        calls.append((agent_id, deal_id, fields, discrepancy, approval_request_id))
        return {"ok": True, "decision": "allow", "crm": fields}

    monkeypatch.setattr("agent.revmem_client.write_crm", fake_write_crm)

    result = runner._execute_tool(
        "write_crm",
        {
            "deal_id": "globex",
            "fields": {"annual_schedule_usd": [80000, 120000, 160000]},
            "discrepancy": {"deal_id": "globex", "amount_usd": 40000, "change_type": "schedule_change"},
            "approval_request_id": "req-1",
        },
        "agent-1",
        "session-1",
    )

    assert result["ok"] is True
    assert calls[0][0] == "agent-1"
    assert calls[0][1] == "globex"


def test_route_for_approval_tool_injects_agent_id(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_route_for_approval(**kwargs: object) -> dict[str, object]:
        calls.append(kwargs)
        return {"approval_request_id": "req-1", "route_to": "controller"}

    monkeypatch.setattr("agent.revmem_client.route_for_approval", fake_route_for_approval)

    result = runner._execute_tool(
        "route_for_approval",
        {
            "deal_id": "globex",
            "amount_usd": 40000,
            "change_type": "schedule_change",
            "summary": "Schedule mismatch",
        },
        "agent-1",
        "session-1",
    )

    assert result["approval_request_id"] == "req-1"
    assert calls == [
        {
            "agent_id": "agent-1",
            "deal_id": "globex",
            "amount_usd": 40000.0,
            "change_type": "schedule_change",
            "summary": "Schedule mismatch",
        }
    ]


def test_get_approval_status_tool_executes_client_call(monkeypatch) -> None:
    def fake_get_approval_status(approval_request_id: str) -> dict[str, str]:
        return {"approval_request_id": approval_request_id, "status": "approved"}

    monkeypatch.setattr("agent.revmem_client.get_approval_status", fake_get_approval_status)

    result = runner._execute_tool("get_approval_status", {"approval_request_id": "req-1"}, "agent-1", "session-1")

    assert result == {"approval_request_id": "req-1", "status": "approved"}
