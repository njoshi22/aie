# RevMem — Architecture Plan (v2)

**Hackathon: AI Engineer World's Fair 2026 · 24h · 3 people**
**Theme: Continual Learning (primary) + Self-Improvement Stack**
**Special prize in reach: Best Usage of Gemini 3.5 ($5k)**

---

## What We're Building

RevMem is the **governed memory + reputation layer** that sits on top of a Gemini Managed Agent and makes its cross-session autonomy safe for finance.

The demo's hero is the **agent's behavior**, not a dashboard. An autonomous Gemini agent receives a newly-signed customer contract, reconciles its pricing against the CRM (mock Salesforce), routes discrepancies to the correct approver, and — across sessions — **visibly gets smarter and earns broader autonomy** because RevMem governs and improves its memory.

**Demo story in 60 seconds**: Agent gets a signed contract → reconciles against CRM → the cold agent over-escalates a rounding artifact _and_ misses a material ramp restructuring → RevMem captures the lesson from that outcome → next session the agent ignores the noise, catches the ramp, and routes it correctly → reputation rises, permissions expand → by session three it auto-reconciles low-risk corrections itself and escalates only genuine judgment calls.

### Two statefulness layers (this is the pitch)

- **Antigravity env-ID** gives _raw_ session continuity (files, terminal, code state).
- **RevMem** adds the _governed, reputation-scored, policy-bounded_ memory layer that makes that continuity safe in a regulated domain.

RevMem sits **on top of** the Gemini primitive — that is the Self-Improvement-Stack story, and a far stronger claim than "we called the Gemini API."

---

## Hackathon-Rules Compliance (non-negotiable)

The 2026 rules disqualify several patterns. The architecture is built to avoid them:

| Banned pattern                                        | How we avoid it                                                                                                                                                                   |
| ----------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Streamlit applications**                            | No Streamlit, and no web dashboard at all — the agent-working view is a **CLI (Rich)**. The only web surface is a single CFO approval page reached from an email link.            |
| **Any project where a dashboard is the main feature** | The autonomous agent workflow is the main feature, shown as a live terminal transcript. Reputation/routing are thin overlays _embedded in the CLI_, never a standalone dashboard. |
| **Basic RAG applications**                            | The hero is an _experiential continual-learning loop_ (agent learns from its own mistake). The policy is framed as a **governance boundary**, never "document ingestion."         |

Demo must show only what we built during the event and clearly identify it. Repo public.

---

## Decisions Made

| Decision             | Choice                                                                                      | Why                                                                                                                                              |
| -------------------- | ------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| Agent runtime        | **Gemini Managed Agents (Antigravity, `antigravity-preview-05-2026`)** via Interactions API | Bleeding-edge → scores the 40% technicality weight; env-ID statefulness _is_ the continual-learning substrate; eligible for the $5k Gemini prize |
| Memory substrate     | **SQLite (stdlib, `db/revmem.db`)** + embedding-cosine rerank                               | Zero infra; persists on the local demo disk; the demo's retrieval intelligence is the reputation rerank, not the store                           |
| Data interface       | **Structured JSON** (agent reads contract/CRM via tools)                                    | Reliable; keeps the heavy reasoning off flaky UI automation                                                                                      |
| API + exposure       | **FastAPI run locally, exposed via ngrok tunnel**                                           | The hosted agent needs a reachable URL; ngrok gives instant reloads, local logs, no deploy cycle                                                 |
| Agent view           | **CLI (Rich) live transcript**                                                              | Streamlit / dashboard-as-main-feature are banned; a terminal transcript foregrounds agent behavior                                               |
| Approval surface     | **One FastAPI-served HTML page**, reached from an email link                                | Minimal web surface; co-located with the governance engine that owns the approval record                                                         |
| Approval gate        | **Server-enforced in the Governance Engine at `write_crm`**                                 | The hosted agent is untrusted/non-deterministic — the financial control cannot live in the agent                                                 |
| Skills / permissions | **Tier-scoped `AGENTS.md` + `SKILL.md`, regenerated per session**                           | Permission expansion becomes a native Antigravity feature, enforced server-side at the tool layer                                                |
| Scenario             | Contract → CRM pricing reconciliation + approver routing                                    | Recognizable enterprise workflow with a natural governance moment                                                                                |
| Deployment           | Local SQLite + local FastAPI + ngrok tunnel + hosted agent (Google)                         | Nothing in the critical path depends on a managed service                                                                                        |
| Demo format          | Pre-run S1 + S2, **live S3**, recorded fallback                                             | De-risks the 20% live-demo score                                                                                                                 |

---

## System Architecture

```
┌─────────────────────────────────────────────────────────┐
│ Gemini Managed Agent  (Antigravity, hosted by Google)    │
│   env-ID → runtime continuity                            │
│   AGENTS.md + SKILL.md → skills gated by reputation tier  │
└───────────────┬──────────────────────────────────────────┘
                │ calls tools ▼ (Interactions API, via ngrok URL)
┌───────────────┴──────────────────────────────────────────┐
│ RevMem API   (FastAPI · local · exposed via ngrok)        │
│   ├─ Context Engine    → embedding-cosine retrieval       │
│   │                       reranked by reputation          │
│   ├─ Governance Engine → policy → approver routing;       │
│   │                       tier → allowed tools;           │
│   │                       authorize_write (approval gate) │
│   ├─ Reputation Engine → outcome-weighted score + tiering  │
│   └─ Approval page     → served HTML (the one web surface) │
└───────────────┬───────────────────────────┬───────────────┘
                │                           │ email link
        ┌───────┴────────┐          ┌───────┴──────────────┐
        │ SQLite         │          │ CFO Approval page    │
        │ db/revmem.db   │          │ (approve / reject)   │
        │ memories,      │          └──────────────────────┘
        │ sessions,      │          ┌──────────────────────┐
        │ agents, policy,│◄─────────│ CLI agent view (Rich) │
        │ approvals, CRM │  reads   │ live transcript +     │
        └────────────────┘          │ rep / routing overlay │
                                    └──────────────────────┘
```

---

## Two Improvement Axes (kept rigorously separate)

**1. Continual learning — the hero (theme-critical, _not_ RAG).**
The agent learns the **ramp lesson** — _"TCV parity is insufficient for ramped deals; reconcile the annual schedule"_ — from **its own Session-1 mistake**. The reviewer's correction on the S1 outcome creates one experiential memory. It is retrieved in later sessions via embedding cosine and reranked by reputation-weighted relevance.

**2. Governance — config, framed as a "boundary" (never "doc ingestion").**
A delegation-of-authority (DOA) policy drives **approver routing** (AM → Controller → CFO/CCO by materiality). Editing the policy re-routes live. This is the _Adaptive Governance_ feature, distinct from reputation tiers.

> **Permission tiers** (earned via reputation) = what the _agent_ may do unsupervised.
> **Policy routing** (org-configured) = the org's rules on _who approves what_.
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
    embedding: list[float]     # embedded for cosine rerank
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

class Approval(BaseModel):
    id: str
    deal_id: str
    discrepancy: dict          # {amount_usd, change_type, field, ...}
    approver_role: str         # am | controller | cfo | cco
    status: str                # pending | approved | rejected
    token: str                 # guards the email link
    created_at: datetime
    decided_at: datetime | None

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
    ANALYST = "analyst"        # 0.3–0.6: + auto-resolve immaterial, store lessons; no CRM writes
    AUTONOMOUS = "autonomous"  # 0.6–1.0: + auto-reconcile policy-covered fixes; escalate only judgment calls
```

---

## Agent Tools (reputation-gated via SKILL.md, enforced server-side)

| Tool                                                | Purpose                                                                                                           | Tier gate                                                                                |
| --------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| `get_contract(deal_id)` / `get_crm_record(deal_id)` | Fetch structured order form + CRM record                                                                          | any                                                                                      |
| `retrieve_context(deal_type, query)`                | Embedding-cosine retrieval of experiential memories + active policy                                               | any                                                                                      |
| `route_for_approval(discrepancy)`                   | Governance picks approver per policy, **creates a pending Approval**, emits the email link, returns `approval_id` | any                                                                                      |
| `write_crm(deal_id, fields, approval_id)`           | Reconcile CRM to the signed contract — **server-gated by `authorize_write`**                                      | AUTONOMOUS only; policy-covered fixes may self-reconcile, judgment changes need approval |
| `log_outcome(session_id, decisions, result)`        | Close session → triggers reputation + relevance updates                                                           | any                                                                                      |
| `store_memory(...)`                                 | Persist an experiential lesson                                                                                    | **ANALYST+**                                                                             |

Each session, RevMem generates a **tier-scoped `SKILL.md`**: higher reputation declares more skills → broader autonomy. The Governance Engine re-checks tier at the tool layer as defense-in-depth.

### Approval Gate (server-enforced — the agent is never the control)

The financial control lives in RevMem, not the hosted agent. Flow:

1. `route_for_approval(discrepancy)` → Governance picks the approver per policy, inserts a **pending `Approval`**, returns a tokenized link (email is **stubbed** for the demo — the link is printed into the CLI transcript for the presenter).
2. The CFO opens the **single served HTML page** (`GET /approvals/{id}?token=…`) and approves/rejects (`POST /approvals/{id}/decision`).
3. If the **agent** has `write_crm` in `allowed_tools`, it polls `GET /approvals/{id}/status` (JSON; cooperative UX only) and then calls `write_crm`. Analysts can route and poll but still cannot mutate CRM.
4. `write_crm` calls `governance.authorize_write(tier, discrepancy, approval_status)` — the **only** thing that can mutate CRM — which returns:

```
ALLOW            # AUTONOMOUS + policy-covered change, OR AUTONOMOUS + a matching approved record
NEEDS_APPROVAL   # material, no approval yet → agent must route_for_approval first
DENY             # OBSERVER/ANALYST, rejected, or beyond-authority → escalate, never write
```

A misbehaving or jailbroken agent still cannot write without the right tier and, when required, a real approved record. Approval alone does not grant analyst CRM write access. `schedule_change` is policy-covered (reconcile CRM to the signed contract); `discount_over_authority` is a judgment change that needs a human even at AUTONOMOUS.

---

## Reputation & Retrieval Algorithms

```
After each session:
  success_rate    = successful_sessions / total_sessions     # success = accuracy >= 0.5
  avg_accuracy    = mean(accuracy over all completed sessions)
  reputation      = 0.6*success_rate + 0.4*avg_accuracy
  reputation      = clamp(reputation, 0.0, 1.0)

  tier = OBSERVER if rep < 0.3 else ANALYST if rep < 0.6 else AUTONOMOUS

Memory relevance update:
  for each memory used in session:
    relevance_score += 0.1 if session succeeded else -0.05  (clamped 0..1)
  unused for 3+ sessions: relevance_score *= 0.95

Retrieval rerank (Context Engine):
  score = α*cosine_similarity + β*relevance_score + γ*recency      # α=0.5, β=0.4, γ=0.1
```

Real reranking driven by embedding cosine — not keyword matching. (Embeddings via `google-genai`
`gemini-embedding-001`, with a deterministic local fallback so dev/tests run offline.)

---

## Demo Scenario — behavior-first

**Deal:** Acme Corp signs a 3-year SaaS subscription (Enterprise Platform, 1,000 seats). The **signed order form is the source of truth**; Salesforce holds the stale deal-desk quote.

**The hero mismatch (Acme):**

| Field               | Signed contract                    | Salesforce (stale)               | Verdict                     |
| ------------------- | ---------------------------------- | -------------------------------- | --------------------------- |
| Seats               | 1,000                              | 1,000                            | match                       |
| **TCV**             | **$450,000**                       | **$450,000**                     | **match ← the trap**        |
| **Annual schedule** | **$100k / $150k / $200k (ramped)** | **$150k / $150k / $150k (flat)** | **MISMATCH — material**     |
| Discount            | 10%                                | 10%                              | match                       |
| Y1 monthly invoice  | $8,333.33                          | $8,333.00                        | $0.33 rounding — immaterial |

The trap: **TCV reconciles, so a naive total-check passes.** The ramp restructuring wrecks Year-1 revenue and ARR timing (material), while the $0.33 artifact tempts an over-flag.

### Session 1 — Cold start (rep 0.1, OBSERVER)

No prior deals → RevMem has genuinely nothing learned (the weakness is _real_, not faked). Agent sees TCV matches → "looks fine," then escalates the **$0.33 rounding** to the CFO (no routing rule yet) and **misses the ramp**. Outcome logged; reviewer correction → creates the one experiential memory.
**Outcome:** `{material_caught: 0/1, false_escalations: 1, accuracy: 0.0}` → rep ~0.2, OBSERVER.

### Session 2 — Same Acme contract (rep 0.2, OBSERVER)

Retrieves the ramp memory → **ignores the rounding, catches the ramp, escalates only that** to the correct approver. **Permission tier unchanged** — isolating the variable: the improvement is **pure RevMem context**, not expanded permissions.
**Outcome:** `{material_caught: 1/1, false_escalations: 0, accuracy: 1.0}` → rep ~0.5 → **ANALYST**.

### Session 3 — LIVE, new Globex contract (rep ~0.5, ANALYST)

Different numbers, same archetype (ramp $80k/$120k/$160k vs flat $120k×3; TCV $360k matches again). The lesson **generalizes** (keyed on `deal_type`, not Acme's numbers). The agent **silently dismisses the immaterial rounding** (an ANALYST capability it lacked as OBSERVER), catches the ramp, and escalates it with a recommended correction. Even after **live approval** (presenter clicks Approve on the served approval page), the ANALYST tier cannot execute the CRM write itself.
**Live flourish:** edit the governance boundary on stage ($1k → $5k threshold) and re-run to show routing shift in real time.
**Optional judgment twist:** Globex contract has a 25% discount vs deal-desk max 20% → agent reconciles the ramp **but correctly escalates the over-authority discount** to the CFO.
**Outcome:** `{material_caught: 1/1, false_escalations: 0, accuracy: 1.0}` → rep ~0.65 → **AUTONOMOUS** (next deal, it could reconcile policy-covered fixes unattended).

Reputation track: **0.1 → 0.2 → 0.5 → 0.65** · tiers **OBSERVER → OBSERVER → ANALYST → AUTONOMOUS**.

The two transitions cleanly separate the two effects:

- **S1 → S2:** smarter context, **same permissions** (isolates "RevMem made it smarter").
- **S2 → S3:** permissions **expand**, unlocking new actions.

---

## How It Scores the Rubric

| Criterion                    | Weight | Our story                                                                                                                                               |
| ---------------------------- | ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Technicality**             | 40%    | Antigravity managed agent + env-ID statefulness + embedding-cosine reranking + server-enforced governance/approval/reputation engine. Hard to recreate. |
| **Creativity & Originality** | 25%    | Governed, reputation-earned autonomy in finance — not a wrapper chatbot.                                                                                |
| **Live Demo**                | 20%    | S1/S2 pre-run; S3 live (approval page + policy edit) with recorded fallback.                                                                            |
| **Future Potential**         | 15%    | The missing infra layer for safely deploying improving agents in regulated domains.                                                                     |

---

## Repo Structure

```
revmem/
├── api/                  ← [Person B] FastAPI server (local, ngrok-exposed)
│   ├── main.py
│   └── routes.py         # agent tools + served approval page + decision endpoint
├── core/                 ← [Person B] memory + governance + reputation
│   ├── models.py         # Pydantic models (shared)
│   ├── database.py       # SQLite connection, schema, row CRUD (incl. approvals)
│   ├── context.py        # embedding retrieval + reranking
│   ├── governance.py     # routing; tier gating; authorize_write; SKILL.md generation
│   ├── reputation.py     # score + tier
│   └── session.py        # lifecycle + outcome logging
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
├── notify/               ← [Person C] email + approval stand-in
│   ├── email.py          # Resend email (magic link) + console dry-run fallback
│   └── approve.py        # scaffold approval endpoints mirroring Person B's contract,
│                         #   until the RevMem API lands (then it drops out)
├── cli/                  ← [Person C] Rich terminal agent view (the main feature)
│   ├── run.py            # live transcript; drives the scaffold reconcile + approval flow
│   └── render.py         # Rich renderables (diff table, reputation bar, routing panels)
├── requirements.txt
└── README.md
```

---

## Work Split

### Person A — Antigravity owner (starts hour 0, highest risk)

1. Interactions API: spin up a managed agent, confirm a round-trip call (**by hour 4**)
2. env-ID threading for cross-session continuity
3. `AGENTS.md` persona + tier-scoped `SKILL.md` generation
4. Tool wiring to the RevMem ngrok URL (via `REVMEM_BASE_URL`), incl. the approval poll
5. Acme / Globex scenario scripting + expected outcomes
6. Local-Gemini-loop fallback if Antigravity isn't working by hour 8

### Person B — RevMem core + API (hour 0–16)

1. `core/models.py` (30m)
2. `core/database.py` — SQLite schema + CRUD, incl. approvals (1h)
3. `core/context.py` — retrieve + rerank (2h)
4. `core/governance.py` — routing + tier gating + `authorize_write` + SKILL.md (2h)
5. `core/reputation.py` — score + tier (1h)
6. `core/session.py` — lifecycle + outcome → triggers updates (1h)
7. `api/` — FastAPI endpoints + approval page; expose via ngrok (2h)
8. `data/` — Acme + Globex contracts, stale CRM, DOA policy, seed (2h)
9. Integration with Person A (2h)

> Detailed task-by-task plan: `docs/superpowers/plans/2026-06-27-revmem-person-b-core-api.md`

### Person C — Agent view CLI (Rich) + notification (hour 0–16)

1. `cli/render.py` + `cli/run.py` — Rich live agent transcript (the **main feature**) (3h)
2. Reputation + routing overlays embedded in the transcript (2h)
3. `notify/email.py` — single CFO approval email (Resend + dry-run fallback) (2h)
4. `notify/approve.py` — scaffold approval endpoints mirroring Person B's contract, so the CLI runs before the API lands (2h)
5. Polish; at integration, point `REVMEM_BASE_URL` at Person B's API and drop the stand-in (3h)

> The **canonical** approval endpoints + SQLite store + `authorize_write` gate are **Person B's**. Person C owns the email, the CLI view, and the page styling. Polling the approval status is the **agent's** (Person A's) job via Person B's `/approvals/{id}/status`; the CLI polls only as a stand-in until that agent is wired.

### Everyone — last 8 hours

| Hours | Activity                                           |
| ----- | -------------------------------------------------- |
| 16–18 | Full integration: run 3 sessions end-to-end        |
| 18–20 | Bug fixes, scenario tuning, rehearsal              |
| 20–22 | Record 1-min video + S3 fallback recording; README |
| 22–24 | Final polish, rehearse live S3, push public repo   |

---

## Timeline Checkpoints

| Hour | Checkpoint      | Must be true                                                                                                                                         |
| ---- | --------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| 4    | **Skeleton**    | Antigravity round-trip call works; SQLite seeded; CLI renders; models defined                                                                        |
| 8    | **Pieces work** | Retrieve+rerank works; agent reconciles mock data; approval page resolves; CLI shows a live run. **Antigravity go/no-go → else local-loop fallback** |
| 12   | **Integration** | Agent calls RevMem tools through ngrok, routes for approval, stores memory; CLI reads from same store                                                |
| 16   | **Demo flow**   | 3 sessions run end-to-end; improvement + permission expansion + approval gate visible                                                                |
| 20   | **Polish**      | S3 rehearsed; edge cases handled; routing live-edit works                                                                                            |
| 24   | **Ship**        | Video recorded, README written, repo public, ngrok tunnel stable                                                                                     |

---

## Risk Mitigation

| Risk                                           | Mitigation                                                                                                  |
| ---------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| Antigravity flakes / unfamiliar                | One owner from hour 0; go/no-go at hour 8; **local-Gemini-loop fallback** (keeps themes, forfeits $5k only) |
| Live S3 breaks                                 | Pre-run S1/S2; recorded S3 fallback                                                                         |
| Reads as a "dashboard project" (disqualifying) | Agent view is a CLI transcript; the only web page is the approval surface                                   |
| Reads as "basic RAG" (disqualifying)           | Lead with the experiential learning loop; call policy a "governance boundary"                               |
| Agent writes CRM without approval              | `authorize_write` is server-side; no approved record → no write, regardless of agent behavior               |
| Hosted agent can't reach RevMem                | Expose via ngrok with a **reserved domain** (stable URL); agent reads `REVMEM_BASE_URL` (no hardcode)       |
| Tunnel drops on venue wifi                     | Phone hotspot backup; disable laptop sleep; pre-run S1/S2 so only S3 needs the live tunnel                  |
| Email delivery flaky                           | Email is stubbed — the approval link is printed in the CLI; presenter opens it directly                     |
| Embedding API latency                          | Pre-embed memories at write time; cache S1/S2 runs                                                          |

---

## Tech Stack

```
Python 3.11+      — RevMem core + API + CLI (uv)
FastAPI           — API server + served approval page (local, exposed via ngrok)
SQLite            — single-file store (stdlib sqlite3)
Pydantic          — data models
google-genai      — Gemini Interactions API (Antigravity) + embeddings
Rich              — CLI agent-working view (NOT Streamlit, no web dashboard)
ngrok             — public tunnel to the local API (reserved domain)
```

---

## Quick Start (for README)

```bash
# RevMem API
uv pip install -r requirements.txt
export GEMINI_API_KEY=...           # aistudio.google.com/api-keys
uv run python -m data.seed          # seed contracts, CRM, policy → db/revmem.db
uv run uvicorn api.main:app --host 0.0.0.0 --port 8000

# Expose to the hosted agent + approval page
ngrok http 8000 --domain=<your-reserved>.ngrok.app
# Person A + CLI set REVMEM_BASE_URL to the ngrok URL

# CLI agent view (+ approval-page stand-in until Person B's API serves it)
uv run uvicorn notify.approve:app --port 8000   # CFO approval page + status endpoint
uv run python -m cli.run                          # the live agent transcript

# Run demo sessions
uv run python -m agent.scenarios    # Acme S1, Acme S2, Globex S3
```
