# RevMem – Governed, Self-Improving Agent Memory & Context Layer for Finance & RevOps

**Hackathon Project Spec — AI Engineer World's Fair 2026**
**Themes**: Continual Learning (primary) + The Self-Improvement Stack
**Special prize targeted**: Best Usage of Gemini 3.5 ($5k)

**Date**: June 27, 2026
**Team Strengths**: Finance/RevOps/Legal domain expertise + Data Science (modeling, feedback systems)

---

## 1. Project Title & One-Liner

**RevMem** (RevOps Memory Layer)

The governed memory + reputation layer that sits on top of a Gemini Managed Agent and makes its cross-session autonomy *safe* for finance — so an autonomous agent reconciling signed contracts against the CRM gets measurably better, and earns broader permissions, the more it is used.

---

## 2. Problem Statement

Finance and RevOps teams want to deploy autonomous agents for high-value work, but face critical blockers:

- Agents forget domain knowledge across sessions and re-make the same mistakes
- They require constant human re-explaining of rules, history, and patterns
- Lack of verifiable identity, evolving trust, and governance makes enterprises unwilling to let agents act on real systems (CRM, billing, ERP)
- There is no reliable way for an agent to improve in production without heavy oversight

Existing memory tools are too generic and lack the governance, auditability, and finance-specific continual-learning loops real teams need.

---

## 3. Solution Overview

**RevMem** is middleware that provides:

- Persistent, structured memory optimized for finance/RevOps concepts (contracts, pricing, approval policy)
- Self-improving retrieval that gets better at surfacing relevant context based on past outcomes
- An identity + reputation system so agents progressively earn trust and broader permissions
- Adaptive governance: a policy-driven approval-routing boundary, separate from earned autonomy
- Full auditability for compliance-heavy environments

A Gemini Managed Agent connects to RevMem and becomes more capable over time with minimal human intervention — directly fulfilling the **Continual Learning** theme, while RevMem itself is **Self-Improvement-Stack** infrastructure.

---

## 4. Focused Use Case (the demo)

A new customer is signed and sends over the **finalized, signed contract**. An autonomous agent must:

1. **Parse** the order form into a normalized pricing table
2. **Reconcile** every pricing field against the CRM record (mock Salesforce)
3. **Route** each discrepancy to the correct approver per the org's delegation-of-authority policy (AM → Controller → CFO/CCO by materiality)
4. **On approval**, reconcile the CRM to the signed contract (the contract is the source of truth)

**Without RevMem** (cold): the agent compares totals, sees TCV matches, declares success — missing a subtle ramp-schedule mismatch — while over-escalating an immaterial rounding artifact.

**With RevMem** (warm): it retrieves the lesson learned from that exact mistake — *"TCV parity isn't enough; reconcile the annual schedule"* — ignores the noise, catches the material item, and routes it accurately. Reputation rises; permissions expand.

---

## 5. Key Features (MVP)

| Feature | Description | Continual-Learning Benefit |
|---------|-------------|-----------------------------|
| Structured Finance Memory | SQLite schema for pricing rules, contract terms, materiality thresholds (embeddings stored per memory) | Consolidates observations into reusable knowledge |
| Self-Improving Retrieval | Embedding-cosine retrieval reranked by reputation-weighted relevance (`α·cosine + β·relevance + γ·recency`) | Learns what context actually helps |
| Agent Identity & Reputation | Dynamic reputation score from observed reconciliation outcomes | Reputation grows with demonstrated competence |
| Adaptive Governance | Policy-driven approver routing + permission tiers that expand with reputation + a server-enforced approval gate on CRM writes | Self-adjusting trust boundaries the agent can't bypass |
| Audit & Observability | Trace of memory usage, routing decisions, and outcomes | Enables evaluation of learning quality |
| Feedback & Reflection | Outcome logging that updates memory relevance + reputation | Core mechanism for continuous improvement |

---

## 6. Technical Architecture

**Core Components**:

- **Agent Runtime**: Gemini **Managed Agents (Antigravity, `antigravity-preview-05-2026`)** via the Interactions API. Stateful sessions via environment ID; skills declared in `AGENTS.md` / `SKILL.md`.
- **Memory Store**: SQLite (single file, `db/revmem.db`) with per-memory embeddings for cosine retrieval.
- **Context Engine**: embedding retrieval + outcome-based reranking.
- **Reputation & Identity Module**: reputation updater driven by observed success/failure; permission-tier mapping.
- **Governance Engine**: policy → approver routing; reputation tier → allowed tools; per-session `SKILL.md` generation; **server-enforced write-approval gate (`authorize_write`)**.
- **Interface Layer**: FastAPI run locally, exposed via an ngrok tunnel — tools the hosted agent calls, plus the served approval page.
- **Agent view**: a Rich CLI live transcript (the main feature). The only web surface is a single FastAPI-served CFO approval page reached from an email link.

**Data Flow**:
Agent receives signed contract → calls RevMem tools (retrieve context, reconcile, route) → outcome logged → memory relevance + reputation updated → future retrievals and permissions improve automatically.

---

## 7. Gemini 3.5 Integration (Prize Path)

**Managed Agents (Antigravity)** is the core runtime, not a stretch goal:

- **Interactions API**: spin up a hosted autonomous agent that reasons and executes natively in an isolated Google-hosted environment.
- **Stateful Memory**: pass the environment ID forward to resume sessions with state intact — the runtime substrate for cross-session learning.
- **Skills Definition**: `AGENTS.md` + `SKILL.md` declare the "RevOps Finance Agent" persona; RevMem regenerates a **tier-scoped `SKILL.md`** each session so capabilities visibly expand as reputation grows.

Two statefulness layers tell the story: Antigravity's env-ID gives raw continuity; **RevMem adds the governed, reputation-scored, policy-bounded memory layer** that makes continuity safe in finance. This is "agentic workflows that improve themselves over time" — not a wrapper chatbot.

---

## 8. Demo Scenario & User Flow

**Scenario**: An agent reconciles newly-signed contracts against the CRM across three sessions, getting smarter and more autonomous each time.

1. **Session 1 (Cold)**: rep 0.1, OBSERVER. No memory yet → over-escalates a $0.33 rounding artifact and misses a material ramp-schedule mismatch (TCV matched, so a naive check passes). Reviewer correction → creates one experiential memory.
2. **Session 2 (Same contract)**: rep 0.2, OBSERVER. Retrieves the lesson → ignores the noise, catches the ramp, routes it correctly. *Same permission tier* — isolating that the gain is pure context. → rep ~0.5, upgrades to ANALYST.
3. **Session 3 (New contract, LIVE)**: rep ~0.5, ANALYST. Lesson generalizes; agent silently dismisses the immaterial noise, catches the ramp, and routes it for approval, but still cannot execute the CRM write itself. Live flourish: edit the governance policy on stage and watch routing change in real time. → rep ~0.65, AUTONOMOUS.

**Key demo moments**:
- Quality of retrieved context improves between Session 1 and Session 2 (same input, better behavior)
- Reputation rises and permission tier expands across sessions
- The agent makes a smarter escalation/routing decision in later sessions

---

## 9. Continual-Learning Mechanisms (Primary Theme)

- **Memory Consolidation**: an outcome correction becomes a reusable, retrievable lesson (not raw logging)
- **Outcome-Based Adaptation**: past success reranks future retrieval (`α·cosine + β·relevance + γ·recency`)
- **Reputation-Driven Learning**: higher reputation unlocks broader permissions and looser governance
- **Generalization**: lessons key on `deal_type`, so they transfer to new deals (not memorization)
- **Minimal Intervention**: once seeded, improvement compounds with usage

---

## 10. Governance, Identity & Trust

- Dynamic reputation scoring from observed behavior (correct catches, correct routing, no false escalations)
- **Permission tiers** earned via reputation (what the *agent* may do unsupervised)
- **Policy-driven approver routing** (the *org's* rules on who approves what) — a governance boundary, kept distinct from reputation
- **Server-enforced approval gate**: CRM writes pass through `authorize_write`; the untrusted hosted agent cannot mutate the system of record without the `AUTONOMOUS` tier and any required approved record
- Complete audit trail of memory usage and decisions

---

## 11. Scope for the Hackathon

**Must Have**:
- SQLite memory store + embedding-cosine retrieval with reputation reranking
- Reputation scoring + permission tiers
- Gemini Managed Agents (Antigravity) runtime with stateful sessions
- Policy-driven approver routing + server-enforced approval gate (single served approval page)
- Three sessions demonstrating measurable improvement + expanding autonomy
- Rich CLI agent-working view (overlays embedded)

**Nice to Have**: live policy-edit re-routing on stage; the over-authority-discount judgment twist in S3; deeper graph relationships.

**Out of Scope**: real Salesforce integration; production-grade infra; on-chain identity; multi-agent orchestration.

**Banned-pattern guardrails (disqualification risk)**: no Streamlit; the dashboard is never the main feature (agent behavior is); the policy is a governance boundary, never "document ingestion" (avoids the basic-RAG trap).

---

## 12. Why This Wins

- **Theme alignment**: a visible Continual-Learning story (same input → better behavior; expanding autonomy) and Self-Improvement-Stack infrastructure.
- **Technicality (40% of judging)**: Antigravity managed agent + env-ID statefulness + embedding-cosine reranking + governance/reputation engine — hard to recreate in a weekend.
- **Gemini prize**: core, creative use of Managed Agents — not a wrapper.
- **Differentiation**: domain-specific (finance/RevOps) + governance + continual learning. Not another generic memory tool.
- **Demo impact**: judges see an agent become measurably more capable and more autonomous at meaningful work.
- **Team fit**: finance/RevOps/legal domain knowledge + data-science strength in feedback and evaluation systems.

---

## 13. Post-Hackathon Vision

**Short-term**: expand to a full MCP server; deeper graph memory; additional finance schemas; substrate-agnostic memory (pluggable to mem0/Zep).

**Long-term**: the trusted memory + governance layer that finance and RevOps platforms use to safely deploy fleets of agents that improve over time.

**VC Narrative**: "The missing infrastructure layer that makes governed, continually improving agents viable in regulated finance and RevOps workflows — combining memory infrastructure with agent identity/trust, with strong founder-market fit."

---

**Document Version**: 2.0
**Status**: Ready for hackathon execution
