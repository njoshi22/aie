from core import database
from core.models import Agent, Approval, ApprovalStatus, Memory, MemoryType, PolicyRule


def test_agent_roundtrip(conn):
    a = Agent(name="A")
    database.insert_agent(conn, a)
    got = database.get_agent(conn, a.id)
    assert got is not None and got.name == "A" and got.reputation_score == 0.1


def test_memory_list_filter(conn):
    a = Agent(name="A")
    database.insert_agent(conn, a)
    m1 = Memory(session_id="s", agent_id=a.id, type=MemoryType.PRICING_FIELD_RULE,
                content="schedule", embedding=[0.1, 0.2])
    m2 = Memory(session_id="s", agent_id=a.id, type=MemoryType.CONTRACT_TERM, content="term")
    database.insert_memory(conn, m1)
    database.insert_memory(conn, m2)
    only = database.list_memories(conn, a.id, MemoryType.PRICING_FIELD_RULE)
    assert len(only) == 1 and only[0].embedding == [0.1, 0.2]


def test_crm_mutable(conn):
    database.upsert_crm(conn, "acme", {"tcv": 450000})
    database.upsert_crm(conn, "acme", {"tcv": 450000, "schedule": [100, 150, 200]})
    assert database.get_crm(conn, "acme") == {"tcv": 450000, "schedule": [100, 150, 200]}


def test_policy_roundtrip(conn):
    r = PolicyRule(description="rounding", condition={"max_usd": 1000}, route_to="am")
    database.upsert_policy(conn, r)
    rules = database.list_policy(conn)
    assert len(rules) == 1 and rules[0].route_to == "am"


def test_grouped_approvals_round_trip(conn):
    approvals = [
        Approval(
            request_id="req-1",
            method="crm.write",
            join="all",
            step_id="cfo",
            deal_id="globex",
            discrepancy={"deal_id": "globex", "change_type": "discount_over_authority"},
            approver_role="cfo",
        ),
        Approval(
            request_id="req-1",
            method="crm.write",
            join="all",
            step_id="cco",
            depends_on=["cfo"],
            deal_id="globex",
            discrepancy={"deal_id": "globex", "change_type": "discount_over_authority"},
            approver_role="cco",
        ),
    ]

    database.insert_approvals(conn, approvals)

    got = database.list_approvals_for_request(conn, "req-1")
    assert [approval.step_id for approval in got] == ["cfo", "cco"]
    assert got[1].depends_on == ["cfo"]
    assert got[0].status == ApprovalStatus.PENDING
