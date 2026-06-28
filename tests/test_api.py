import pytest
from fastapi.testclient import TestClient

from api.main import create_app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db = tmp_path / "api.db"
    monkeypatch.setenv("REVMEM_DB", str(db))
    monkeypatch.setattr("core.context.embed_text", lambda t: [1.0, 0.0])
    app = create_app()
    with TestClient(app) as c:
        yield c


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


def test_write_crm_denied_for_observer(client):
    aid = client.post("/agents", json={"name": "A"}).json()["id"]
    r = client.post("/crm/write",
                    json={"agent_id": aid, "deal_id": "acme",
                          "fields": {"annual_schedule_usd": [100000, 150000, 200000]}})
    assert r.status_code == 403


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
