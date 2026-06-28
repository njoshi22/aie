from data import seed
from core import database
from core.models import Approval


def test_seed_is_idempotent(conn):
    a1 = seed.seed(conn)
    a2 = seed.seed(conn)
    assert a1.id == a2.id  # does not create a second agent
    assert len(database.list_policy(conn)) == 5
    crm = database.get_crm(conn, "acme")
    assert crm is not None
    assert crm["annual_schedule_usd"] == [150000, 150000, 150000]


def test_seed_clears_approval_tasks_for_repeatable_demo(conn):
    database.insert_approval(
        conn,
        Approval(
            request_id="req-1",
            method="crm.write",
            deal_id="acme",
            discrepancy={"deal_id": "acme", "change_type": "schedule_change"},
            approver_role="controller",
        ),
    )

    seed.seed(conn)

    assert database.list_approvals_for_request(conn, "req-1") == []


def test_load_contract():
    c = seed.load_contract("acme")
    assert c is not None
    assert c["annual_schedule_usd"] == [100000, 150000, 200000]
    assert seed.load_contract("nope") is None
