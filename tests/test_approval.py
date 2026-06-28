import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from core import database, governance
from core.governance import WriteDecision
from core.models import ApprovalStatus, PermissionTier


def test_authorize_write_decisions():
    sched = {"change_type": "schedule_change", "amount_usd": 0}
    disc = {"change_type": "discount_over_authority", "amount_usd": 5}
    assert governance.authorize_write(PermissionTier.OBSERVER, sched) == WriteDecision.DENY
    # OBSERVER is denied even WITH an approval — the tier check must win over approval status.
    assert governance.authorize_write(PermissionTier.OBSERVER, sched, ApprovalStatus.APPROVED) == WriteDecision.DENY
    assert governance.authorize_write(PermissionTier.ANALYST, sched) == WriteDecision.NEEDS_APPROVAL
    assert governance.authorize_write(PermissionTier.ANALYST, sched, ApprovalStatus.APPROVED) == WriteDecision.ALLOW
    assert governance.authorize_write(PermissionTier.ANALYST, sched, ApprovalStatus.REJECTED) == WriteDecision.DENY
    assert governance.authorize_write(PermissionTier.AUTONOMOUS, sched) == WriteDecision.ALLOW
    assert governance.authorize_write(PermissionTier.AUTONOMOUS, disc) == WriteDecision.NEEDS_APPROVAL


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("REVMEM_DB", str(tmp_path / "a.db"))
    monkeypatch.setattr("core.context.embed_text", lambda t: [1.0, 0.0])
    app = create_app()
    with TestClient(app) as c:
        yield c


def _make_analyst(client) -> str:
    aid = client.post("/agents", json={"name": "A"}).json()["id"]
    conn = client.app.state.conn
    agent = database.get_agent(conn, aid)
    agent.permission_tier = PermissionTier.ANALYST
    database.update_agent(conn, agent)
    return aid


def test_full_approval_flow(client):
    aid = _make_analyst(client)
    disc = {"deal_id": "acme", "amount_usd": 0, "change_type": "schedule_change"}
    routed = client.post("/route_for_approval", json=disc).json()
    assert routed["route_to"] == "controller" and routed["status"] == "pending"
    assert "token" not in routed and "approval_link" not in routed  # agent must not receive the secret
    approval_id = routed["approval_id"]
    tok = database.get_approval(client.app.state.conn, approval_id).token

    body = {"agent_id": aid, "deal_id": "acme",
            "fields": {"annual_schedule": [100000, 150000, 200000]},
            "discrepancy": disc, "approval_id": approval_id}
    assert client.post("/crm/write", json=body).status_code == 403  # pending → blocked

    page = client.get(f"/approvals/{approval_id}", params={"token": tok})
    assert page.status_code == 200 and "Approve" in page.text
    dec = client.post(f"/approvals/{approval_id}/decision",
                      data={"decision": "approve", "token": tok})
    assert dec.json()["status"] == "approved"

    assert client.post("/crm/write", json=body).status_code == 200  # approved → allowed
    assert client.get("/crm/acme").json()["annual_schedule"] == [100000, 150000, 200000]


def test_approval_scope_bypass_blocked(client):
    aid = _make_analyst(client)
    disc = {"deal_id": "acme", "amount_usd": 0, "change_type": "schedule_change"}
    routed = client.post("/route_for_approval", json=disc).json()
    approval_id = routed["approval_id"]
    tok = database.get_approval(client.app.state.conn, approval_id).token

    # Approve the "acme" approval
    client.post(f"/approvals/{approval_id}/decision", data={"decision": "approve", "token": tok})

    fields = {"annual_schedule": [100000]}
    # Using acme's approval_id to authorize a write to a DIFFERENT deal must be blocked
    body_globex = {"agent_id": aid, "deal_id": "globex", "fields": fields,
                   "discrepancy": disc, "approval_id": approval_id}
    assert client.post("/crm/write", json=body_globex).status_code == 403

    # The same approval still authorizes the matching "acme" write
    body_acme = {"agent_id": aid, "deal_id": "acme", "fields": fields,
                 "discrepancy": disc, "approval_id": approval_id}
    assert client.post("/crm/write", json=body_acme).status_code == 200
