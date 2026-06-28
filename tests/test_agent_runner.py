from __future__ import annotations

from agent.runner import ToolCallRecord, _execute_tool


def test_tool_call_record_shape() -> None:
    record: ToolCallRecord = {
        "name": "route_for_approval",
        "arguments": {"deal_id": "globex", "change_type": "schedule_change"},
        "result": {"approval_id": "appr-1", "route_to": "controller"},
    }

    assert record["name"] == "route_for_approval"
    assert record["arguments"]["deal_id"] == "globex"
    assert record["result"]["route_to"] == "controller"


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
