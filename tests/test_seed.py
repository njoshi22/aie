from data import seed
from core import database


def test_seed_is_idempotent(conn):
    a1 = seed.seed(conn)
    a2 = seed.seed(conn)
    assert a1.id == a2.id  # does not create a second agent
    assert len(database.list_policy(conn)) == 5
    assert database.get_crm(conn, "acme")["annual_schedule"] == [150000, 150000, 150000]


def test_load_contract():
    c = seed.load_contract("acme")
    assert c["annual_schedule"] == [100000, 150000, 200000]
    assert seed.load_contract("nope") is None
