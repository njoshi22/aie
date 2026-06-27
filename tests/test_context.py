from datetime import datetime, timezone

from core import context, database
from core.models import Agent, Memory, MemoryType


def test_cosine_basic():
    assert context.cosine([1, 0], [1, 0]) == 1.0
    assert context.cosine([1, 0], [0, 1]) == 0.0
    assert context.cosine([], [1, 0]) == 0.0


def test_retrieve_orders_by_relevance(conn, monkeypatch):
    # deterministic embeddings: identical vector so cosine term is constant
    monkeypatch.setattr(context, "embed_text", lambda t: [1.0, 0.0])
    a = Agent(name="A")
    database.insert_agent(conn, a)
    low = Memory(session_id="s", agent_id=a.id, type=MemoryType.PRICING_FIELD_RULE,
                 content="low", embedding=[1.0, 0.0], relevance_score=0.2)
    high = Memory(session_id="s", agent_id=a.id, type=MemoryType.PRICING_FIELD_RULE,
                  content="high", embedding=[1.0, 0.0], relevance_score=0.9)
    database.insert_memory(conn, low)
    database.insert_memory(conn, high)
    out = context.retrieve(conn, a.id, query="anything", limit=2)
    assert [m.content for m in out] == ["high", "low"]
    assert database.get_memory(conn, high.id).access_count == 1
