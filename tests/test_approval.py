import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from api.approval_gate import ensure_method_approved
from core import database, governance
from core.governance import WriteDecision
from core.models import ApprovalStatus, PermissionTier


def test_authorize_write_decisions():
    sched = {"change_type": "schedule_change", "amount_usd": 0}
    disc = {"change_type": "discount_over_authority", "amount_usd": 5}
    assert governance.authorize_write(PermissionTier.OBSERVER, sched) == WriteDecision.DENY
    # OBSERVER is denied even WITH an approval — the tier check must win over approval status.
    assert governance.authorize_write(PermissionTier.OBSERVER, sched, ApprovalStatus.APPROVED) == WriteDecision.DENY
    assert governance.authorize_write(PermissionTier.ANALYST, sched) == WriteDecision.DENY
    assert governance.authorize_write(PermissionTier.ANALYST, sched, ApprovalStatus.APPROVED) == WriteDecision.DENY
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


def _make_agent(client: TestClient, tier: str) -> str:
    aid = client.post("/agents", json={"name": "A"}).json()["id"]
    conn = client.app.state.conn
    agent = database.get_agent(conn, aid)
    assert agent is not None
    agent.permission_tier = tier
    database.update_agent(conn, agent)
    return aid


def _approve_request(client: TestClient, request_id: str) -> None:
    approvals = database.list_approvals_for_request(client.app.state.conn, request_id)
    for approval in approvals:
        response = client.post(
            f"/approvals/{approval.id}/decision",
            data={"decision": "approve", "token": approval.token},
        )
        assert response.status_code == 200


def test_gate_creates_all_approval_request_with_dependencies(client):
    conn = client.app.state.conn
    result = ensure_method_approved(
        conn,
        "crm.write",
        {
            "tier": PermissionTier.ANALYST,
            "deal_id": "globex",
            "discrepancy": {
                "deal_id": "globex",
                "amount_usd": 0,
                "change_type": "discount_over_authority",
            },
        },
    )

    assert result.allowed is False
    assert result.payload["approval_required"] is True
    assert result.payload["approval_join"] == "all"
    assert [approval["role"] for approval in result.payload["approvals"]] == ["cfo", "cco"]
    assert result.payload["approvals"][1]["depends_on"] == ["cfo"]


def test_gate_allows_any_request_after_one_approval(client):
    conn = client.app.state.conn
    result = ensure_method_approved(conn, "policy.update", {"tier": PermissionTier.ANALYST})
    request_id = result.payload["approval_request_id"]
    first = database.list_approvals_for_request(conn, request_id)[0]
    first.status = ApprovalStatus.APPROVED
    database.update_approval(conn, first)

    allowed = ensure_method_approved(conn, "policy.update", {"tier": PermissionTier.ANALYST}, request_id)

    assert allowed.allowed is True
    assert allowed.payload["approval_required"] is False


def test_gate_denies_mismatched_approval_request_context(client):
    conn = client.app.state.conn
    discrepancy = {
        "deal_id": "acme",
        "amount_usd": 40000,
        "change_type": "schedule_change",
    }
    result = ensure_method_approved(
        conn,
        "crm.write",
        {"tier": PermissionTier.ANALYST, "deal_id": "acme", "discrepancy": discrepancy},
    )
    request_id = result.payload["approval_request_id"]
    approval = database.list_approvals_for_request(conn, request_id)[0]
    approval.status = ApprovalStatus.APPROVED
    database.update_approval(conn, approval)

    mismatched = ensure_method_approved(
        conn,
        "crm.write",
        {"tier": PermissionTier.ANALYST, "deal_id": "globex", "discrepancy": discrepancy},
        request_id,
    )

    assert mismatched.allowed is False
    assert mismatched.payload["decision"] == "deny"


def test_full_approval_flow(client):
    aid = _make_agent(client, PermissionTier.AUTONOMOUS)
    disc = {"deal_id": "globex", "amount_usd": 0, "change_type": "discount_over_authority"}
    routed = client.post("/route_for_approval", json={"agent_id": aid, **disc}).json()
    assert routed["route_to"] == "cfo_cco" and routed["status"] == "pending"
    assert "token" not in routed and "approval_link" not in routed  # agent must not receive the secret
    approval_id = routed["approval_id"]
    approval = database.get_approval(client.app.state.conn, approval_id)
    assert approval is not None

    body = {"agent_id": aid, "deal_id": "globex",
            "fields": {"discount_pct": 30},
            "discrepancy": disc, "approval_request_id": routed["approval_request_id"]}
    pending = client.post("/crm/write", json=body)
    assert pending.status_code == 202
    assert pending.json()["approval_status"] == "pending"

    page = client.get(f"/approvals/{approval_id}", params={"token": approval.token})
    assert page.status_code == 200 and "Approve" in page.text
    _approve_request(client, routed["approval_request_id"])

    assert client.post("/crm/write", json=body).status_code == 200  # approved → allowed
    assert client.get("/crm/globex").json()["discount_pct"] == 30


def test_analyst_crm_write_blocked_even_with_approval(client):
    aid = _make_agent(client, PermissionTier.ANALYST)
    disc = {"deal_id": "acme", "amount_usd": 40000, "change_type": "schedule_change"}
    routed = client.post("/route_for_approval", json={"agent_id": aid, **disc}).json()
    _approve_request(client, routed["approval_request_id"])

    body = {"agent_id": aid, "deal_id": "acme",
            "fields": {"annual_schedule_usd": [100000, 150000, 200000]},
            "discrepancy": disc, "approval_request_id": routed["approval_request_id"]}

    assert client.post("/crm/write", json=body).status_code == 403
    assert client.get("/crm/acme").json()["annual_schedule_usd"] == [150000, 150000, 150000]


def test_approval_scope_bypass_blocked(client):
    aid = _make_agent(client, PermissionTier.AUTONOMOUS)
    disc = {"deal_id": "acme", "amount_usd": 0, "change_type": "discount_over_authority"}
    routed = client.post("/route_for_approval", json={"agent_id": aid, **disc}).json()
    _approve_request(client, routed["approval_request_id"])

    fields = {"discount_pct": 30}
    # Using acme's approval_id to authorize a write to a DIFFERENT deal must be blocked
    body_globex = {"agent_id": aid, "deal_id": "globex", "fields": fields,
                   "discrepancy": disc, "approval_request_id": routed["approval_request_id"]}
    assert client.post("/crm/write", json=body_globex).status_code == 403

    # The same approval still authorizes the matching "acme" write
    body_acme = {"agent_id": aid, "deal_id": "acme", "fields": fields,
                 "discrepancy": disc, "approval_request_id": routed["approval_request_id"]}
    assert client.post("/crm/write", json=body_acme).status_code == 200
