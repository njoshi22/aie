from __future__ import annotations

import hashlib
import math
import os
import sqlite3
from datetime import datetime, timezone

from core import database
from core.models import Memory

EMBED_DIM = 256
ALPHA, BETA, GAMMA = 0.5, 0.4, 0.1


def embed_text(text: str) -> list[float]:
    key = os.getenv("GEMINI_API_KEY")
    if key:
        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=key)
            result = client.models.embed_content(
                model="gemini-embedding-001",
                contents=text,
                config=types.EmbedContentConfig(output_dimensionality=EMBED_DIM),
            )
            emb = result.embeddings
            if emb is None or emb[0].values is None:
                raise ValueError("no embeddings returned")
            return list(emb[0].values)
        except Exception:
            pass
    return _hash_embed(text)


def _hash_embed(text: str) -> list[float]:
    vec = [0.0] * EMBED_DIM
    for token in text.lower().split():
        idx = int(hashlib.md5(token.encode()).hexdigest(), 16) % EMBED_DIM
        vec[idx] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _recency(created_at: datetime, now: datetime) -> float:
    age_days = max((now - created_at).total_seconds() / 86400.0, 0.0)
    return 1.0 / (1.0 + age_days)


def score_memory(m: Memory, query_emb: list[float], now: datetime) -> float:
    return (ALPHA * cosine(query_emb, m.embedding)
            + BETA * m.relevance_score
            + GAMMA * _recency(m.created_at, now))


# Organization-wide lessons (e.g. approver feedback) are stored under this scope and
# surfaced to every agent's retrieve, like the policy — they are not tied to one agent.
SHARED_MEMORY_AGENT_ID = "__shared__"


def retrieve(conn: sqlite3.Connection, agent_id: str, query: str,
             memory_type: str | None = None, limit: int = 5,
             now: datetime | None = None) -> list[Memory]:
    now = now or datetime.now(timezone.utc)
    memories = database.list_memories(conn, agent_id, memory_type)
    if agent_id != SHARED_MEMORY_AGENT_ID:
        memories += database.list_memories(conn, SHARED_MEMORY_AGENT_ID, memory_type)
    query_emb = embed_text(query)
    ranked = sorted(memories, key=lambda m: score_memory(m, query_emb, now), reverse=True)
    top = ranked[:limit]
    for m in top:
        m.access_count += 1
        m.last_used_at = now
        database.update_memory(conn, m)
    return top
