from __future__ import annotations

import importlib
from typing import Any
import urllib.error

import pytest


def _reload_client(
    monkeypatch: pytest.MonkeyPatch,
    base_url: str | None,
    stub_mode: str | None = None,
) -> Any:
    if base_url is None:
        monkeypatch.delenv("REVMEM_BASE_URL", raising=False)
        monkeypatch.delenv("REVMEM_API_URL", raising=False)
    else:
        monkeypatch.setenv("REVMEM_BASE_URL", base_url)
    if stub_mode is None:
        monkeypatch.delenv("REVMEM_STUB_MODE", raising=False)
    else:
        monkeypatch.setenv("REVMEM_STUB_MODE", stub_mode)
    import agent.revmem_client as client

    return importlib.reload(client)


def test_live_http_error_does_not_fall_back_to_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _reload_client(monkeypatch, "https://example.ngrok.app")

    def fail(*args: object, **kwargs: object) -> object:
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(client.urllib.request, "urlopen", fail)

    with pytest.raises(client.RevMemApiError):
        client.ensure_agent("RevOps Finance Agent")


def test_stub_mode_must_be_explicit_when_base_url_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _reload_client(monkeypatch, "https://example.ngrok.app", "1")

    assert client.ensure_agent("RevOps Finance Agent")["id"] == "revops-agent-1"


def test_no_base_url_defaults_to_stub_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _reload_client(monkeypatch, None)

    assert client.start_session("a1", "reconcile")["status"] == "running"


def test_retrieve_context_preserves_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _reload_client(monkeypatch, None)

    def fake_api(method: str, path: str, body: dict[str, object] | None = None) -> dict[str, object]:
        assert method == "GET"
        assert path.startswith("/memory/retrieve?")
        assert body is None
        return {"memories": [{"id": "mem-1"}], "policy": [{"id": "DOA-003"}]}

    monkeypatch.setattr(client, "_api_call", fake_api)

    assert client.retrieve_context("agent-1", "ramp") == {
        "memories": [{"id": "mem-1"}],
        "policy": [{"id": "DOA-003"}],
    }


def test_client_route_status_write_shapes(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _reload_client(monkeypatch, None)
    calls: list[tuple[str, str, dict[str, object] | None]] = []

    def fake_api(method: str, path: str, body: dict[str, object] | None = None) -> dict[str, object]:
        calls.append((method, path, body))
        if path == "/route_for_approval":
            return {"approval_id": "appr-1", "route_to": "controller", "status": "pending"}
        if path == "/approvals/appr-1/status":
            return {"id": "appr-1", "status": "approved"}
        if path == "/crm/write":
            assert body is not None
            return {"ok": True, "decision": "allow", "crm": body["fields"]}
        raise AssertionError(path)

    monkeypatch.setattr(client, "_api_call", fake_api)

    routed = client.route_for_approval("acme", 40000, "schedule_change")
    status = client.get_approval_status(routed["approval_id"])
    written = client.write_crm(
        "agent-1",
        "acme",
        {"annual_schedule_usd": [100000, 150000, 200000]},
        {"deal_id": "acme", "amount_usd": 40000, "change_type": "schedule_change"},
        "appr-1",
    )

    assert status["status"] == "approved"
    assert written["ok"] is True
    assert calls == [
        ("POST", "/route_for_approval", {"deal_id": "acme", "amount_usd": 40000, "change_type": "schedule_change"}),
        ("GET", "/approvals/appr-1/status", None),
        (
            "POST",
            "/crm/write",
            {
                "agent_id": "agent-1",
                "deal_id": "acme",
                "fields": {"annual_schedule_usd": [100000, 150000, 200000]},
                "discrepancy": {"deal_id": "acme", "amount_usd": 40000, "change_type": "schedule_change"},
                "approval_id": "appr-1",
            },
        ),
    ]
