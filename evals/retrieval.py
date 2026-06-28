"""Retrieval-quality eval: does RevMem surface the RIGHT lesson?

The learning curve shows the agent acts better; this shows *why* - the context
engine retrieves the relevant lesson for the task at hand. Builds a small labeled
probe set over a throwaway store, runs the real ``core.context.retrieve`` (cosine
+ reputation-weighted relevance + recency), and reports hit@1 / hit@3 / MRR.

It also runs an ablation: with the reputation-driven ``relevance_score`` learned
(reinforced lessons score higher) vs flattened to the 0.5 default. A positive MRR
lift is direct evidence that outcome-based learning improves retrieval, not just
behavior.

Offline the embedding is a deterministic hash-bag (keyword cosine); with
GEMINI_API_KEY it is gemini-embedding-001. Either way the rerank is real.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

# Candidate lessons (the store). `relevance` is the learned/reinforced signal a
# successful past use would have produced.
CANDIDATES = [
    {
        "key": "ramp",
        "type": "pricing_field_rule",
        "relevance": 0.9,
        "content": "TCV parity is insufficient for ramped deals; reconcile the annual "
        "payment schedule, not just the total contract value.",
    },
    {
        "key": "rounding",
        "type": "materiality_threshold",
        "relevance": 0.7,
        "content": "Sub-dollar monthly invoice differences are rounding artifacts; "
        "auto-dismiss them per DOA-001 instead of escalating.",
    },
    {
        "key": "discount",
        "type": "pricing_field_rule",
        "relevance": 0.8,
        "content": "Discounts above 20 percent exceed deal-desk authority; escalate the "
        "discount to the CFO and CCO for approval.",
    },
    {
        "key": "terms",
        "type": "contract_term",
        "relevance": 0.5,
        "content": "Net 30 payment terms are standard for enterprise subscription contracts.",
    },
]

# Probes: each task query has exactly one relevant lesson it should surface first.
PROBES = [
    {"query": "ramp annual payment schedule mismatch reconcile total contract value", "relevant": "ramp"},
    {"query": "monthly invoice rounding difference immaterial dismiss", "relevant": "rounding"},
    {"query": "discount exceeds deal desk authority escalate cfo approval", "relevant": "discount"},
]


def _build_store(conn, agent_id: str, candidates: list[dict], relevance_overrides: dict | None = None) -> dict:
    from core import context, database
    from core.models import Memory

    overrides = relevance_overrides or {}
    key_to_id: dict[str, str] = {}
    for c in candidates:
        memory = Memory(
            session_id="eval",
            agent_id=agent_id,
            type=c["type"],
            content=c["content"],
            embedding=context.embed_text(c["content"]),
            relevance_score=overrides.get(c["key"], c["relevance"]),
        )
        database.insert_memory(conn, memory)
        key_to_id[c["key"]] = memory.id
    return key_to_id


def _rank_of(results: list, target_id: str) -> int | None:
    for i, m in enumerate(results, start=1):
        if m.id == target_id:
            return i
    return None


def evaluate_retrieval(limit: int = 4, relevance_overrides: dict | None = None) -> dict:
    """Run every probe through the real retriever and score the ranking."""
    from core import context, database

    agent_id = "eval-agent"
    with tempfile.TemporaryDirectory() as tmp:
        conn = database.get_connection(Path(tmp) / "retrieval-eval.db")
        database.init_db(conn)
        keys = _build_store(conn, agent_id, CANDIDATES, relevance_overrides)

        per_probe = []
        hit1 = hit3 = 0
        reciprocal = 0.0
        for probe in PROBES:
            results = context.retrieve(conn, agent_id, probe["query"], limit=limit)
            rank = _rank_of(results, keys[probe["relevant"]])
            per_probe.append(
                {
                    "query": probe["query"],
                    "relevant": probe["relevant"],
                    "rank": rank,
                    "top": results[0].content[:60] if results else None,
                }
            )
            if rank == 1:
                hit1 += 1
            if rank and rank <= 3:
                hit3 += 1
            if rank:
                reciprocal += 1.0 / rank
        conn.close()

    n = len(PROBES)
    return {
        "n": n,
        "hit@1": round(hit1 / n, 3),
        "hit@3": round(hit3 / n, 3),
        "mrr": round(reciprocal / n, 3),
        "per_probe": per_probe,
    }


# Competitive pair: two lessons with near-identical keywords to the query. The
# "stale" one is a verbatim keyword match (high cosine) but was superseded, so its
# relevance decayed; the "correct" lesson carries the real rule plus extra context
# (lower cosine) but earned trust through successful outcomes (high relevance).
# Cosine alone picks the stale note; the reputation-weighted relevance should not.
COMPETITIVE_QUERY = "ramp annual payment schedule reconcile"
COMPETITIVE = [
    {
        "key": "correct",
        "type": "pricing_field_rule",
        "relevance": 0.95,  # reinforced by past successful reconciliations
        "content": "ramp annual payment schedule reconcile against the signed contract "
        "as the source of truth, not just the total contract value",
    },
    {
        "key": "stale",
        "type": "pricing_field_rule",
        "relevance": 0.2,   # an earlier note, since superseded; relevance decayed
        "content": "ramp annual payment schedule reconcile",
    },
]


def _competitive_rank(relevance_overrides: dict | None = None) -> int | None:
    from core import context, database

    agent_id = "eval-agent"
    with tempfile.TemporaryDirectory() as tmp:
        conn = database.get_connection(Path(tmp) / "retrieval-ablation.db")
        database.init_db(conn)
        keys = _build_store(conn, agent_id, COMPETITIVE, relevance_overrides)
        results = context.retrieve(conn, agent_id, COMPETITIVE_QUERY, limit=len(COMPETITIVE))
        rank = _rank_of(results, keys["correct"])
        conn.close()
    return rank


def relevance_ablation() -> dict[str, Any]:
    """Does the reputation-driven relevance signal improve retrieval?

    On a keyword-ambiguous query, compare the rank of the correct (trusted) lesson
    with learned relevance vs a flat 0.5 baseline. A rank improvement is direct
    evidence that outcome-based learning, not just lexical overlap, drives retrieval.
    """
    learned_rank = _competitive_rank()
    flat_rank = _competitive_rank(relevance_overrides={c["key"]: 0.5 for c in COMPETITIVE})
    rr_learned = (1.0 / learned_rank) if learned_rank else 0.0
    rr_flat = (1.0 / flat_rank) if flat_rank else 0.0
    return {
        "query": COMPETITIVE_QUERY,
        "scenario": "two keyword-similar lessons; the trusted one should win",
        "learned_rank": learned_rank,
        "flat_rank": flat_rank,
        "rank_improved": bool(learned_rank and flat_rank and learned_rank < flat_rank),
        "mrr_lift": round(rr_learned - rr_flat, 3),
    }


def run() -> dict:
    return {"quality": evaluate_retrieval(), "ablation": relevance_ablation()}
