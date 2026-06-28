import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from core import database
from core.models import ApprovalStatus, PermissionTier


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db = tmp_path / "api.db"
    monkeypatch.setenv("REVMEM_DB", str(db))
    monkeypatch.setattr("core.context.embed_text", lambda t: [1.0, 0.0])
    app = create_app()
    with TestClient(app) as c:
        yield c


def _make_agent(client, tier: str = PermissionTier.ANALYST) -> str:
    agent_id = client.post("/agents", json={"name": f"A-{tier}"}).json()["id"]
    conn = client.app.state.conn
    agent = database.get_agent(conn, agent_id)
    assert agent is not None
    agent.permission_tier = tier
    database.update_agent(conn, agent)
    return agent_id


def test_agent_and_skill(client):
    aid = client.post("/agents", json={"name": "A"}).json()["id"]
    assert client.post("/agents", json={"name": "A"}).json()["id"] == aid  # idempotent by name
    got = client.get(f"/agents/{aid}").json()
    assert got["permission_tier"] == "observer"
    assert "write_crm" not in got["allowed_tools"]
    skill = client.get(f"/agents/{aid}/skill.md").text
    assert "RevOps Finance Agent" in skill


def test_route_for_approval(client):
    r = client.post("/route_for_approval",
                    json={"amount_usd": 40000, "change_type": "schedule_change"})
    assert r.json()["route_to"] == "controller"
    r = client.post("/route_for_approval",
                    json={"amount_usd": 0, "change_type": "discount_over_authority"})
    assert r.json()["route_to"] == "cfo_cco"


def test_route_for_approval_uses_db_policy_for_created_approval_role(client):
    conn = client.app.state.conn
    rule = database.get_policy(conn, "DOA-003")
    assert rule is not None
    rule.route_to = "finance_admin"
    database.upsert_policy(conn, rule)

    routed = client.post(
        "/route_for_approval",
        json={"deal_id": "acme", "amount_usd": 40000, "change_type": "schedule_change"},
    ).json()

    assert routed["route_to"] == "finance_admin"
    assert [approval["role"] for approval in routed["approvals"]] == ["finance_admin"]


def test_write_crm_denied_for_observer(client):
    aid = client.post("/agents", json={"name": "A"}).json()["id"]
    r = client.post("/crm/write",
                    json={"agent_id": aid, "deal_id": "acme",
                          "fields": {"annual_schedule_usd": [100000, 150000, 200000]}})
    assert r.status_code == 403


def test_crm_write_uses_method_approval_request_flow(client):
    agent_id = _make_agent(client)
    body = {
        "agent_id": agent_id,
        "deal_id": "acme",
        "fields": {"annual_schedule_usd": [100000, 150000, 200000]},
        "discrepancy": {"deal_id": "acme", "amount_usd": 40000, "change_type": "schedule_change"},
    }

    pending = client.post("/crm/write", json=body)

    assert pending.status_code == 202
    payload = pending.json()
    assert payload["approval_required"] is True
    assert payload["approval_join"] == "all"
    assert payload["approvals"][0]["role"] == "controller"
    assert "token" not in payload
    request_id = payload["approval_request_id"]
    status = client.get(f"/approval-requests/{request_id}/status").json()
    assert status["approval_status"] == "pending"
    assert "token" not in status

    approval_id = payload["approvals"][0]["approval_id"]
    approval = database.get_approval(client.app.state.conn, approval_id)
    assert approval is not None
    decided = client.post(
        f"/approvals/{approval_id}/decision",
        data={"decision": "approve", "token": approval.token},
    )
    assert decided.json()["status"] == ApprovalStatus.APPROVED

    body["approval_request_id"] = request_id
    written = client.post("/crm/write", json=body)
    assert written.status_code == 200
    assert written.json()["approval_request_id"] == request_id
    assert client.get("/crm/acme").json()["annual_schedule_usd"] == [100000, 150000, 200000]


def test_crm_write_uses_db_policy_for_created_approval_role(client):
    agent_id = _make_agent(client)
    conn = client.app.state.conn
    rule = database.get_policy(conn, "DOA-003")
    assert rule is not None
    rule.route_to = "finance_admin"
    database.upsert_policy(conn, rule)

    pending = client.post(
        "/crm/write",
        json={
            "agent_id": agent_id,
            "deal_id": "acme",
            "fields": {"annual_schedule_usd": [100000, 150000, 200000]},
            "discrepancy": {"deal_id": "acme", "amount_usd": 40000, "change_type": "schedule_change"},
        },
    )

    assert pending.status_code == 202
    assert [approval["role"] for approval in pending.json()["approvals"]] == ["finance_admin"]


def test_approval_inbox_shows_pending_links_for_role(client):
    agent_id = _make_agent(client)
    pending = client.post(
        "/crm/write",
        json={
            "agent_id": agent_id,
            "deal_id": "acme",
            "fields": {"annual_schedule_usd": [100000, 150000, 200000]},
            "discrepancy": {"deal_id": "acme", "amount_usd": 40000, "change_type": "schedule_change"},
        },
    )
    approval_id = pending.json()["approvals"][0]["approval_id"]

    inbox = client.get("/approval-inbox/controller")

    assert inbox.status_code == 200
    assert "Controller Approval Inbox" in inbox.text
    assert f"/approvals/{approval_id}?token=" in inbox.text


def test_approval_decision_persists_comment_and_exposes_it_to_polling_agent(client):
    agent_id = _make_agent(client)
    pending = client.post(
        "/crm/write",
        json={
            "agent_id": agent_id,
            "deal_id": "acme",
            "fields": {"annual_schedule_usd": [100000, 150000, 200000]},
            "discrepancy": {"deal_id": "acme", "amount_usd": 40000, "change_type": "schedule_change"},
        },
    ).json()
    approval_id = pending["approvals"][0]["approval_id"]
    request_id = pending["approval_request_id"]
    approval = database.get_approval(client.app.state.conn, approval_id)
    assert approval is not None

    decided = client.post(
        f"/approvals/{approval_id}/decision",
        data={
            "decision": "approve",
            "token": approval.token,
            "comment": "Approved. Use the signed ramp schedule exactly.",
        },
    )
    status = client.get(f"/approval-requests/{request_id}/status").json()

    assert decided.json()["comment"] == "Approved. Use the signed ramp schedule exactly."
    assert status["approvals"][0]["comment"] == "Approved. Use the signed ramp schedule exactly."


def test_trusted_rejection_comment_reroutes_approval_to_mentioned_persona(client):
    agent_id = _make_agent(client)
    body = {
        "agent_id": agent_id,
        "deal_id": "acme",
        "fields": {"annual_schedule_usd": [100000, 150000, 200000]},
        "discrepancy": {"deal_id": "acme", "amount_usd": 40000, "change_type": "schedule_change"},
    }
    pending = client.post("/crm/write", json=body).json()
    request_id = pending["approval_request_id"]
    controller_id = pending["approvals"][0]["approval_id"]
    controller = database.get_approval(client.app.state.conn, controller_id)
    assert controller is not None

    rerouted = client.post(
        f"/approvals/{controller_id}/decision",
        data={
            "decision": "deny",
            "token": controller.token,
            "comment": "Reach out to the CCO for this exception.",
        },
    )
    status = client.get(f"/approval-requests/{request_id}/status").json()
    cco_approvals = [
        approval for approval in database.list_approvals_for_request(client.app.state.conn, request_id)
        if approval.approver_role == "cco"
    ]

    assert rerouted.json()["status"] == ApprovalStatus.REROUTED
    assert rerouted.json()["comment"] == "Reach out to the CCO for this exception."
    assert status["approval_status"] == ApprovalStatus.PENDING
    assert status["approvals"][0]["status"] == ApprovalStatus.REROUTED
    assert status["approvals"][0]["comment"] == "Reach out to the CCO for this exception."
    assert len(cco_approvals) == 1
    assert client.get("/approval-inbox/cco").text.count(f"/approvals/{cco_approvals[0].id}?token=") == 1

    client.post(
        f"/approvals/{cco_approvals[0].id}/decision",
        data={"decision": "approve", "token": cco_approvals[0].token, "comment": "CCO approved."},
    )

    body["approval_request_id"] = request_id
    assert client.post("/crm/write", json=body).status_code == 200


def test_dependent_approval_cannot_be_decided_before_parent(client):
    agent_id = _make_agent(client)
    pending = client.post(
        "/crm/write",
        json={
            "agent_id": agent_id,
            "deal_id": "globex",
            "fields": {"discount_pct": 30},
            "discrepancy": {"deal_id": "globex", "amount_usd": 0, "change_type": "discount_over_authority"},
        },
    )

    assert pending.status_code == 202
    approvals = pending.json()["approvals"]
    assert [approval["role"] for approval in approvals] == ["cfo", "cco"]
    cfo_id = approvals[0]["approval_id"]
    cco_id = approvals[1]["approval_id"]
    cco = database.get_approval(client.app.state.conn, cco_id)
    cfo = database.get_approval(client.app.state.conn, cfo_id)
    assert cco is not None
    assert cfo is not None

    blocked = client.post(
        f"/approvals/{cco_id}/decision",
        data={"decision": "approve", "token": cco.token},
    )
    assert blocked.status_code == 409

    assert client.post(
        f"/approvals/{cfo_id}/decision",
        data={"decision": "approve", "token": cfo.token},
    ).json()["status"] == ApprovalStatus.APPROVED
    assert client.post(
        f"/approvals/{cco_id}/decision",
        data={"decision": "approve", "token": cco.token},
    ).json()["status"] == ApprovalStatus.APPROVED


def test_policy_update_uses_any_approval_method_policy(client):
    policy_id = client.get("/policy").json()[0]["id"]
    pending = client.put(f"/policy/{policy_id}", json={"route_to": "vp_finance"})

    assert pending.status_code == 202
    payload = pending.json()
    assert payload["approval_join"] == "any"
    assert {approval["role"] for approval in payload["approvals"]} == {"finance_admin", "controller"}
    request_id = payload["approval_request_id"]
    approval_id = payload["approvals"][0]["approval_id"]
    approval = database.get_approval(client.app.state.conn, approval_id)
    assert approval is not None
    client.post(
        f"/approvals/{approval_id}/decision",
        data={"decision": "approve", "token": approval.token},
    )

    applied = client.put(
        f"/policy/{policy_id}",
        json={"route_to": "vp_finance", "approval_request_id": request_id},
    )
    assert applied.status_code == 200
    assert applied.json()["route_to"] == "vp_finance"


def test_contracts_and_crm_served(client):
    assert client.get("/contracts/acme").json()["annual_schedule_usd"] == [100000, 150000, 200000]
    assert client.get("/crm/acme").json()["annual_schedule_usd"] == [150000, 150000, 150000]


def test_store_memory_denied_for_observer(client):
    # store_memory is the agent's tool — OBSERVER may not call it (ANALYST+ only)
    aid = client.post("/agents", json={"name": "A"}).json()["id"]
    r = client.post("/memory", json={"session_id": "s", "agent_id": aid,
                                      "type": "pricing_field_rule", "content": "x"})
    assert r.status_code == 403


def test_log_outcome_seeds_lesson_and_keeps_metrics(client):
    # The S1 reviewer correction: log_outcome's `lesson` seeds an experiential memory
    # server-side (NOT the agent's store_memory), and the extra metrics are persisted.
    aid = client.post("/agents", json={"name": "A"}).json()["id"]
    sid = client.post("/sessions", json={"agent_id": aid, "task": "reconcile"}).json()["id"]
    done = client.post(f"/sessions/{sid}/complete", json={
        "accuracy": 0.0, "material_caught": 0, "false_escalations": 1,
        "lesson": {"type": "pricing_field_rule",
                   "content": "TCV parity is insufficient for ramped deals; "
                              "reconcile the annual schedule"},
    }).json()
    assert done["session"]["outcome"]["false_escalations"] == 1
    # The seeded lesson is now retrievable, and retrieve bundles the active policy.
    out = client.get("/memory/retrieve", params={"agent_id": aid, "query": "ramp"}).json()
    assert any("annual schedule" in m["content"] for m in out["memories"])
    assert isinstance(out["policy"], list) and len(out["policy"]) == 5
