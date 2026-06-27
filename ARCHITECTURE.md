# RevMem — Architecture Plan (v2)

**Hackathon: AI Engineer World's Fair 2026 · 24h · 3 people**
**Theme: Continual Learning (primary) + Self-Improvement Stack**
**Special prizes in reach: Best Usage of Gemini 3.5 ($5k) · Best Usage of DigitalOcean**

---

## What We're Building

RevMem is the **governed memory + reputation layer** that sits on top of a Gemini Managed Agent and makes its cross-session autonomy safe for finance.

The demo's hero is the **agent's behavior**, not a dashboard. An autonomous Gemini agent receives a newly-signed customer contract, reconciles its pricing against the CRM (mock Salesforce), routes discrepancies to the correct approver, and — across sessions — **visibly gets smarter and earns broader autonomy** because RevMem governs and improves its memory.

**Demo story in 60 seconds**: Agent gets a signed contract → reconciles against CRM → the cold agent over-escalates a rounding artifact *and* misses a material ramp restructuring → RevMem captures the lesson from that outcome → next session the agent ignores the noise, catches the ramp, and routes it correctly → reputation rises, permissions expand → by session three it auto-reconciles low-risk corrections itself and escalates only genuine judgment calls.

### Two statefulness layers (this is the pitch)

- **Antigravity env-ID** gives *raw* session continuity (files, terminal, code state).
- **RevMem** adds the *governed, reputation-scored, policy-bounded* memory layer that makes that continuity safe in a regulated domain.

RevMem sits **on top of** the Gemini primitive — that is the Self-Improvement-Stack story, and a far stronger claim than "we called the Gemini API."

---

## Hackathon-Rules Compliance (non-negotiable)

The 2026 rules disqualify several patterns. The architecture is built to avoid them:

| Banned pattern | How we avoid it |
|----------------|-----------------|
| **Streamlit applications** | UI is React + Vite. No Streamlit anywhere. |
| **Any project where a dashboard is the main feature** | The autonomous agent workflow is the main feature. Reputation/routing are thin overlays *embedded in the agent view*, never a standalone dashboard. |
| **Basic RAG applications** | The hero is an *experiential continual-learning loop* (agent learns from its own mistake). The policy is framed as a **governance boundary**, never "document ingestion." |

Demo must show only what we built during the event and clearly identify it. Repo public.

---

## Decisions Made

| Decision | Choice | Why |
|----------|--------|-----|
| Agent runtime | **Gemini Managed Agents (Antigravity, `antigravity-preview-05-2026`)** via Interactions API | Bleeding-edge → scores the 40% technicality weight; env-ID statefulness *is* the continual-learning substrate; eligible for the $5k Gemini prize |
| Memory substrate | **MongoDB Atlas (document + Vector Search)** | Partner tool (Atlas Sandbox on GCP); one managed store for docs + vectors; no Docker to babysit live; supports the "hybrid" claim |
| Data interface | **Structured JSON** (agent reads contract/CRM via tools) | Reliable; keeps the heavy reasoning off flaky UI automation |
| API + hosting | **FastAPI on DigitalOcean App Platform** | Hosted agent must reach RevMem; hosting on DO also grabs the DO special prize ($200 credits cover it) |
| UI | **React + Vite** | Streamlit is banned; matches the broader `lex-ui` stack |
| Skills / permissions | **Tier-scoped `AGENTS.md` + `SKILL.md`, regenerated per session** | Permission expansion becomes a native Antigravity feature, enforced server-side at the tool layer |
| Scenario | Contract → CRM pricing reconciliation + approver routing | Recognizable enterprise workflow with a natural governance moment |
| Deployment | Atlas (cloud) + RevMem API (DO) + hosted agent (Google) | No local DB to die mid-demo |
| Demo format | Pre-run S1 + S2, **live S3**, recorded fallback | De-risks the 20% live-demo score |

---

## System Architecture

```
┌─────────────────────────────────────────────────────────┐
│ Gemini Managed Agent  (Antigravity, hosted by Google)    │
│   env-ID → runtime continuity                            │
│   AGENTS.md + SKILL.md → skills gated by reputation tier  │
└───────────────┬──────────────────────────────────────────┘
                │ calls tools ▼ (Interactions API)
┌───────────────┴──────────────────────────────────────────┐
│ RevMem API   (FastAPI · DigitalOcean App Platform)        │
│   ├─ Context Engine    → Atlas Vector Search retrieval    │
│   │                       reranked by reputation          │
│   ├─ Governance Engine → policy → approver routing;       │
│   │                       reputation tier → allowed tools │
│   └─ Reputation Engine → outcome-weighted score + tiering  │
└───────────────┬──────────────────────────────────────────┘
                │
        ┌───────┴────────┐          ┌──────────────────────┐
        │ MongoDB Atlas  │          │ React + Vite UI      │
        │ memories,      │◄─────────│ live agent-working    │
        │ sessions,      │  reads   │ view + reputation /   │
        │ agents, policy,│          │ routing overlays      │
        │ mock CRM       │          │ + approve button (S3) │
        └────────────────┘          └──────────────────────┘
```

---

## Two Improvement Axes (kept rigorously separate)

**1. Continual learning — the hero (theme-critical, *not* RAG).**
The agent learns the **ramp lesson** — *"TCV parity is insufficient for ramped deals; reconcile the annual schedule"* — from **its own Session-1 mistake**. The reviewer's correction on the S1 outcome creates one experiential memory. It is retrieved in later sessions via Atlas Vector Search and reranked by reputation-weighted relevance.

**2. Governance — config, framed as a "boundary" (never "doc ingestion").**
A delegation-of-authority (DOA) policy drives **approver routing** (AM → Controller → CFO/CCO by materiality). Editing the policy re-routes live. This is the *Adaptive Governance* feature, distinct from reputation tiers.

> **Permission tiers** (earned via reputation) = what the *agent* may do unsupervised.
> **Policy routing** (org-configured) = the org's rules on *who approves what*.
> Two governance sources, never blurred.

---

## Core Data Models

```python
# core/models.py

class Memory(BaseModel):
    id: str
    session_id: str
    agent_id: str
    type: str                  # pricing_field_rule | materiality_threshold | contract_term | crm_record
    content: str               # natural-language lesson
    embedding: list[float]     # Atlas Vector Search index
    metadata: dict             # {deal_type, focus_fields, threshold_usd, source, ...}
    relevance_score: float     # starts 0.5, adjusted by outcomes (0.0–1.0)
    access_count: int
    created_at: datetime
    last_used_at: datetime | None

class PolicyRule(BaseModel):
    id: str
    description: str           # "diffs < $1k → AM; schedule changes or > $50k → CFO"
    condition: dict            # {min_usd, max_usd, change_types}
    route_to: str              # am | controller | cfo | cco
    version: int               # editing bumps version (live re-routing)

class Session(BaseModel):
    id: str
    agent_id: str
    env_id: str | None         # Antigravity environment ID (runtime continuity)
    task: str
    status: str                # running | completed | failed
    outcome: dict | None       # {material_caught, false_escalations, routed_correctly, accuracy}
    memories_used: list[str]
    memories_created: list[str]
    started_at: datetime
    ended_at: datetime | None

class Agent(BaseModel):
    id: str
    name: str
    reputation_score: float    # 0.0–1.0
    total_sessions: int
    successful_sessions: int
    permission_tier: str       # observer | analyst | autonomous
    created_at: datetime

class PermissionTier:
    OBSERVER = "observer"      # 0.0–0.3: read + flag/escalate only
    ANALYST = "analyst"        # 0.3–0.6: + auto-resolve immaterial, execute approved corrections
    AUTONOMOUS = "autonomous"  # 0.6–1.0: + auto-reconcile policy-covered fixes; escalate only judgment calls
```

---

## Agent Tools (reputation-gated via SKILL.md, enforced server-side)

| Tool | Purpose | Tier gate |
|------|---------|-----------|
| `get_contract(deal_id)` / `get_crm_record(deal_id)` | Fetch structured order form + CRM record | any |
| `retrieve_context(deal_type, query)` | Atlas vector retrieval of experiential memories + active policy | any |
| `route_for_approval(discrepancy, recommended_approver)` | Governance engine returns approver per policy; emits approval request | any |
| `write_crm(deal_id, corrected_fields)` | Reconcile CRM to the signed contract | **ANALYST+** (denied below → "escalate instead") |
| `log_outcome(session_id, decisions, result)` | Close session → triggers reputation + relevance updates | any |
| `store_memory(...)` | Persist an experiential lesson | **ANALYST+** |

Each session, RevMem generates a **tier-scoped `SKILL.md`**: higher reputation declares more skills → broader autonomy. The Governance Engine re-checks tier at the tool layer as defense-in-depth.

---

## Reputation & Retrieval Algorithms

```
After each session:
  success_rate    = successful_sessions / total_sessions
  recent_accuracy = correct material catches + correct routing − false escalations (recent window)
  reputation      = 0.6*success_rate + 0.3*recent_accuracy + 0.1*efficiency_bonus
  reputation      = clamp(reputation, 0.0, 1.0)

  tier = OBSERVER if rep < 0.3 else ANALYST if rep < 0.6 else AUTONOMOUS

Memory relevance update:
  for each memory used in session:
    relevance_score += 0.1 if session succeeded else -0.05  (clamped 0..1)
  unused for 3+ sessions: relevance_score *= 0.95

Retrieval rerank (Context Engine):
  score = α*cosine_similarity + β*relevance_score + γ*recency      # α=0.5, β=0.4, γ=0.1
```

This is real reranking driven by Atlas vector search — not keyword matching.

---

## Demo Scenario — behavior-first

**Deal:** Acme Corp signs a 3-year SaaS subscription (Enterprise Platform, 1,000 seats). The **signed order form is the source of truth**; Salesforce holds the stale deal-desk quote.

**The hero mismatch (Acme):**

| Field | Signed contract | Salesforce (stale) | Verdict |
|-------|-----------------|--------------------|---------|
| Seats | 1,000 | 1,000 | match |
| **TCV** | **$450,000** | **$450,000** | **match ← the trap** |
| **Annual schedule** | **$100k / $150k / $200k (ramped)** | **$150k / $150k / $150k (flat)** | **MISMATCH — material** |
| Discount | 10% | 10% | match |
| Y1 monthly invoice | $8,333.33 | $8,333.00 | $0.33 rounding — immaterial |

The trap: **TCV reconciles, so a naive total-check passes.** The ramp restructuring wrecks Year-1 revenue and ARR timing (material), while the $0.33 artifact tempts an over-flag.

### Session 1 — Cold start (rep 0.1, OBSERVER)
No prior deals → RevMem has genuinely nothing learned (the weakness is *real*, not faked). Agent sees TCV matches → "looks fine," then escalates the **$0.33 rounding** to the CFO (no routing rule yet) and **misses the ramp**. Outcome logged; reviewer correction → creates the one experiential memory.
**Outcome:** `{material_caught: 0/1, false_escalations: 1, accuracy: 0.0}` → rep ~0.2, OBSERVER.

### Session 2 — Same Acme contract (rep 0.2, OBSERVER)
Retrieves the ramp memory → **ignores the rounding, catches the ramp, escalates only that** to the correct approver. **Permission tier unchanged** — isolating the variable: the improvement is **pure RevMem context**, not expanded permissions.
**Outcome:** `{material_caught: 1/1, false_escalations: 0, accuracy: 1.0}` → rep ~0.5 → **ANALYST**.

### Session 3 — LIVE, new Globex contract (rep ~0.5, ANALYST)
Different numbers, same archetype (ramp $80k/$120k/$160k vs flat $120k×3; TCV $360k matches again). The lesson **generalizes** (keyed on `deal_type`, not Acme's numbers). At ANALYST tier the agent **auto-reconciles the ramp into CRM itself**.
**Live flourish:** edit the governance boundary on stage ($1k → $5k threshold) and re-run to show routing shift in real time.
**Optional judgment twist:** Globex contract has a 25% discount vs deal-desk max 20% → agent auto-fixes the ramp **but correctly escalates the over-authority discount**.
**Outcome:** `{material_caught: 1/1, false_escalations: 0, accuracy: 1.0}` → rep ~0.65 → **AUTONOMOUS**.

Reputation track: **0.1 → 0.2 → 0.5 → 0.65** · tiers **OBSERVER → OBSERVER → ANALYST → AUTONOMOUS**.

The two transitions cleanly separate the two effects:
- **S1 → S2:** smarter context, **same permissions** (isolates "RevMem made it smarter").
- **S2 → S3:** permissions **expand**, unlocking new actions.

---

## How It Scores the Rubric

| Criterion | Weight | Our story |
|-----------|--------|-----------|
| **Technicality** | 40% | Antigravity managed agent + env-ID statefulness + Atlas vector reranking + governance/reputation engine. Hard to recreate. |
| **Creativity & Originality** | 25% | Governed, reputation-earned autonomy in finance — not a wrapper chatbot. |
| **Live Demo** | 20% | S1/S2 pre-run; S3 live with recorded fallback. |
| **Future Potential** | 15% | The missing infra layer for safely deploying improving agents in regulated domains. |

---

## Repo Structure

```
revmem/
├── api/                  ← [Person B] FastAPI server (deploys to DigitalOcean)
│   ├── main.py
│   └── routes.py
├── core/                 ← [Person B] memory + governance + reputation
│   ├── models.py         # Pydantic models (shared)
│   ├── context.py        # Atlas vector retrieval + reranking
│   ├── governance.py     # policy → routing; tier → allowed tools; SKILL.md generation
│   ├── reputation.py     # score + tier
│   ├── session.py        # lifecycle + outcome logging
│   └── atlas.py          # MongoDB Atlas client + vector index
├── agent/                ← [Person A] Antigravity integration
│   ├── runner.py         # Interactions API calls, env-ID threading
│   ├── AGENTS.md         # agent persona
│   ├── SKILL.md          # tier-scoped skills (generated per session)
│   └── scenarios.py      # Acme / Globex scripted scenarios + expected outcomes
├── data/                 ← [Person B] mock finance data
│   ├── contracts.json    # Acme + Globex signed order forms
│   ├── salesforce.json   # stale CRM records
│   ├── policy.json       # DOA policy rules
│   └── seed.py
├── ui/                   ← [Person C] React + Vite
│   ├── src/AgentView.tsx # live agent-working view (the main feature)
│   └── src/overlays/     # reputation + routing overlays, approve button
├── requirements.txt
└── README.md
```

---

## Work Split

### Person A — Antigravity owner (starts hour 0, highest risk)
1. Interactions API: spin up a managed agent, confirm a round-trip call (**by hour 4**)
2. env-ID threading for cross-session continuity
3. `AGENTS.md` persona + tier-scoped `SKILL.md` generation
4. Tool wiring to RevMem API
5. Acme / Globex scenario scripting + expected outcomes
6. Local-Gemini-loop fallback if Antigravity isn't working by hour 8

### Person B — RevMem core + API (hour 0–16)
1. `core/models.py` (30m)
2. `core/atlas.py` — Atlas client + vector index (1h)
3. `core/context.py` — retrieve + rerank (2h)
4. `core/governance.py` — policy routing + tier gating + SKILL.md (2h)
5. `core/reputation.py` — score + tier (1h)
6. `core/session.py` — lifecycle + outcome → triggers updates (1h)
7. `api/` — FastAPI endpoints; deploy to DigitalOcean (1.5h)
8. `data/` — Acme + Globex contracts, stale CRM, DOA policy, seed (2h)
9. Integration with Person A (2h)

### Person C — Agent workflow UI (React + Vite, hour 0–16)
1. Vite skeleton + live agent-working view (the **main feature**) (3h)
2. Reputation + routing overlays embedded in the view (2h)
3. Approve button + live policy-edit control for S3 (2h)
4. Polish, real-time refresh from RevMem API (3h)
5. Integration testing (2h)

### Everyone — last 8 hours
| Hours | Activity |
|-------|----------|
| 16–18 | Full integration: run 3 sessions end-to-end |
| 18–20 | Bug fixes, scenario tuning, rehearsal |
| 20–22 | Record 1-min video + S3 fallback recording; README |
| 22–24 | Final polish, rehearse live S3, push public repo |

---

## Timeline Checkpoints

| Hour | Checkpoint | Must be true |
|------|-----------|--------------|
| 4 | **Skeleton** | Antigravity round-trip call works; Atlas connected; React shell renders; models defined |
| 8 | **Pieces work** | Retrieve+rerank works; agent reconciles mock data; UI shows a live run. **Antigravity go/no-go → else local-loop fallback** |
| 12 | **Integration** | Agent calls RevMem tools, stores memory, UI reads from same store |
| 16 | **Demo flow** | 3 sessions run end-to-end; improvement + permission expansion visible |
| 20 | **Polish** | S3 rehearsed; edge cases handled; routing live-edit works |
| 24 | **Ship** | Video recorded, README written, repo public, DO deploy live |

---

## Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| Antigravity flakes / unfamiliar | One owner from hour 0; go/no-go at hour 8; **local-Gemini-loop fallback** (keeps themes, forfeits $5k only) |
| Live S3 breaks | Pre-run S1/S2; recorded S3 fallback |
| Reads as a "dashboard project" (disqualifying) | Foreground agent behavior; overlays embedded, never standalone |
| Reads as "basic RAG" (disqualifying) | Lead with the experiential learning loop; call policy a "governance boundary" |
| Hosted agent can't reach local RevMem | RevMem API on DigitalOcean; Atlas is cloud — nothing local in the critical path |
| Atlas vector index latency | Pre-embed seed memories; cache S1/S2 runs |

---

## Tech Stack

```
Python 3.11+      — RevMem core + API (uv)
FastAPI           — API server (hosted on DigitalOcean App Platform)
MongoDB Atlas     — document + Vector Search (single store)
Pydantic          — data models
google-genai      — Gemini Interactions API (Antigravity managed agents)
React + Vite       — agent workflow UI (NOT Streamlit)
```

---

## Quick Start (for README)

```bash
# RevMem API
uv pip install -r requirements.txt
export GEMINI_API_KEY=...           # aistudio.google.com/api-keys
export MONGODB_ATLAS_URI=...        # Atlas Sandbox (GCP)
uv run python -m data.seed          # seed contracts, CRM, policy, memories
uv run uvicorn api.main:app         # → RevMem API (deploy target: DigitalOcean)

# UI
cd ui && pnpm install && pnpm dev   # → React agent view

# Run demo sessions
uv run python -m agent.scenarios    # Acme S1, Acme S2, Globex S3
```
