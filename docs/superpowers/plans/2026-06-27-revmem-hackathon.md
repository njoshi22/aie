# RevMem Hackathon Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build RevMem, a governed memory and context layer that shows a finance/revops agent improving across repeated sessions through better retrieval, reputation, governance, and audit visibility.

**Architecture:** Use one TypeScript Next.js app for the hackathon: dashboard, mock finance UIs, REST APIs, and domain services live in one deployable unit. Keep persistence local and explicit with SQLite plus Drizzle, while isolating memory, retrieval, governance, reputation, audit, and Gemini adapters behind typed modules that can move to Postgres, pgvector, Neo4j, or a standalone MCP server after the event.

**Tech Stack:** Next.js App Router, TypeScript strict mode, React, Tailwind, Drizzle ORM, SQLite, Vitest, Playwright, `@google/genai`, Zod.

## Global Constraints

- Build for a 48-hour hackathon first; do not introduce separate services, queues, Kubernetes, event buses, or production identity providers.
- Keep the demo scalable by using clean module boundaries and adapter interfaces, not by prematurely deploying distributed infrastructure.
- MVP must show structured finance memory, self-improving retrieval, agent identity and reputation, adaptive governance, audit/observability, feedback/reflection, Gemini usage, and visible improvement across 2-3 sessions.
- Store graph relationships in relational tables for the MVP; do not add a dedicated graph database during the hackathon.
- Store embeddings as JSON vectors in SQLite for the MVP; design the repository interface so pgvector can replace it after the hackathon.
- Use Gemini through a server-side adapter only; never expose API keys to client components.
- Computer Use integration should feed observations into RevMem. RevMem should not own browser automation in the first build.
- MCP-style shape is a stretch goal; ship REST routes first with request/response contracts that can be wrapped by MCP later.
- Real financial integrations, on-chain identity, production-grade compliance, and complex multi-agent orchestration are out of scope for the hackathon.

---

## Recommended Architecture

### Approach Options

**Recommended: single full-stack Next.js app with typed domain modules.**
This gets the dashboard, mock UIs, APIs, seed data, and demo loop into one repo with one dev command. It is the fastest path to a convincing demo while preserving scale by keeping the core logic in framework-independent `src/core/*` modules.

**Alternative: FastAPI backend plus React frontend.**
This is fine technically, but it doubles bootstrapping, deployment, auth/env handling, and test setup for a hackathon. The split only pays off once the team has external consumers or heavy backend workloads.

**Alternative: MCP server first.**
This is attractive for agent infrastructure, but it risks spending the hackathon on protocol plumbing instead of the visible continual-learning story. Build REST with MCP-shaped contracts first, then wrap the same core services in MCP after the demo.

### System Boundary

RevMem owns memory, retrieval, reputation, governance, audit, mock data, and demo visibility. Gemini/Computer Use is an external agent runtime that interacts with the mock UI and reports observations, decisions, and outcomes back to RevMem.

```text
Gemini / Computer Use Agent
        |
        | observations, retrieval requests, task outcomes
        v
Next.js Route Handlers
        |
        v
Typed RevMem Core
        |
        +-- Memory Store + Retrieval
        +-- Reputation Engine
        +-- Governance Engine
        +-- Reflection Engine
        +-- Audit Log
        |
        v
SQLite + Drizzle
        |
        v
Dashboard + Mock Finance UIs
```

### Domain Model

Use these domain concepts from the spec, but keep the first schema compact:

- `AgentIdentity`: stable agent identity, display name, credential label, current reputation, permission tier.
- `Session`: one cold-start or follow-up run in the demo.
- `Observation`: raw facts captured from mock billing, contract, pipeline, and fee-analysis workflows.
- `Memory`: consolidated knowledge item with type, text, tags, source observations, confidence, usefulness score, and embedding vector.
- `MemoryEdge`: typed relationship between memories, such as `derived_from`, `supports`, `contradicts`, `mentions_customer`, or `mentions_contract`.
- `RetrievalEvent`: record of query, returned memory IDs, ranking scores, and whether the context helped.
- `TaskOutcome`: success, failure, compliance issue, or manual override for an agent task.
- `ReputationEvent`: score delta with reason, rule compliance, and task outcome link.
- `GovernanceDecision`: allowed or denied action with policy inputs, permission tier, and explanation.
- `AuditEvent`: append-only record of important reads, writes, decisions, and reflections.

### Data Flow

1. Agent opens a mock finance UI and attempts a task such as fee leakage detection.
2. Agent sends `ObservationInput` records to RevMem.
3. RevMem consolidates observations into finance-specific memories and relationships.
4. Agent asks for context using a task-specific query.
5. Retrieval ranks memory candidates with lexical score, vector score, recency, usefulness, and task-kind boosts.
6. Governance checks requested action against reputation, task type, and policy rules.
7. Agent completes or fails the task and posts `TaskOutcomeInput`.
8. Reputation and memory usefulness update from the outcome.
9. Dashboard shows session-to-session improvement in context relevance, task success, and permission tier.

### Core Interfaces

Use these TypeScript contracts across API routes, services, and tests.

```ts
export type MemoryKind =
  | "billing_rule"
  | "contract_clause"
  | "pipeline_event"
  | "fee_pattern"
  | "reflection";

export type TaskKind =
  | "fee_leakage_detection"
  | "pipeline_update"
  | "contract_reconciliation";

export type PermissionTier = "observe" | "recommend" | "act_with_approval" | "act";

export type OutcomeStatus = "success" | "failure" | "compliance_blocked" | "manual_override";

export interface ObservationInput {
  agentId: string;
  sessionId: string;
  taskKind: TaskKind;
  source: "computer_use" | "manual_demo" | "seed";
  content: string;
  entities: Record<string, string>;
  occurredAt: string;
}

export interface MemoryRecord {
  id: string;
  kind: MemoryKind;
  title: string;
  body: string;
  tags: string[];
  confidence: number;
  usefulnessScore: number;
  embedding: number[];
  createdAt: string;
  updatedAt: string;
}

export interface RetrievalRequest {
  agentId: string;
  sessionId: string;
  taskKind: TaskKind;
  query: string;
  limit: number;
}

export interface RetrievalResult {
  memory: MemoryRecord;
  score: number;
  reasons: string[];
}

export interface GovernanceRequest {
  agentId: string;
  taskKind: TaskKind;
  action: "read_context" | "recommend_change" | "update_pipeline" | "mark_fee_leakage";
  targetId: string;
}

export interface GovernanceDecision {
  allowed: boolean;
  requiredTier: PermissionTier;
  agentTier: PermissionTier;
  reason: string;
}
```

### Storage Strategy

SQLite is enough for the hackathon if the repository interface is clean. Use Drizzle migrations and avoid ORM magic hidden in components.

- `agents`: identity, credential label, reputation score, permission tier.
- `sessions`: session number, agent ID, task kind, started/completed timestamps.
- `observations`: raw event data and extracted entities.
- `memories`: consolidated memory records and JSON embedding vectors.
- `memory_edges`: graph relationships between memories.
- `retrieval_events`: query, returned memory IDs, ranking components, helpful flag.
- `task_outcomes`: session result and evidence.
- `reputation_events`: score changes.
- `governance_decisions`: policy evaluations.
- `audit_events`: append-only observability trail.
- `mock_contracts`, `mock_invoices`, `mock_pipeline_deals`: demo data shown in the UI.

### Retrieval and Learning

The MVP retrieval score should be transparent and explainable, not fancy:

```text
score =
  0.40 * lexicalMatch
+ 0.25 * vectorSimilarity
+ 0.15 * usefulnessScore
+ 0.10 * taskKindBoost
+ 0.05 * recencyBoost
+ 0.05 * confidence
```

For the first build, vector similarity can use Gemini embeddings if available through the current SDK path. If embeddings are not accessible during implementation, use deterministic local hash vectors behind the same `EmbeddingProvider` interface so the demo and tests still run. The Gemini adapter should still be used for reflection and memory consolidation so the prize path remains real.

### Governance Rules

Keep governance deterministic for the MVP:

- `observe`: can read mock UI and request context.
- `recommend`: can flag suspected leakage and draft pipeline changes.
- `act_with_approval`: can stage updates that require a visible approval.
- `act`: can apply allowed mock updates directly.

Reputation maps to tier:

- `< 35`: `observe`
- `35-64`: `recommend`
- `65-84`: `act_with_approval`
- `85+`: `act`

Outcome scoring:

- Successful task with no compliance issue: `+12`
- Helpful retrieval marked true: `+4`
- Incorrect recommendation: `-8`
- Compliance-blocked action attempt: `-15`
- Manual override required: `-6`

### Demo Narrative

The demo should be tight:

1. Session 1 starts with low reputation and weak/no memories. Agent finds some invoice/contract details but misses at least one fee leakage pattern or gets blocked from an action.
2. RevMem stores observations, consolidates memories, and logs reflection.
3. Session 2 retrieves better context. Agent detects leakage faster, makes fewer irrelevant observations, and earns more reputation.
4. Session 3 shows a higher permission tier and a governed action path, such as staging or applying a pipeline update.
5. Dashboard shows the story in numbers: success rate, relevant memories retrieved, task duration or step count, reputation, permission tier, and audit trail.

### Post-Hackathon Scalability Path

The first scalable upgrade is not microservices. It is replacing internals behind stable interfaces:

1. Move SQLite to Postgres.
2. Replace JSON vector scan with pgvector.
3. Add a dedicated graph store only if graph traversal becomes a bottleneck.
4. Wrap REST routes with an MCP server using the same core services.
5. Add tenant-scoped auth and policy-backed approvals.
6. Add real finance/revops connectors after the mock workflow proves value.

---

## File Structure

Create the app with this structure. Keep route handlers thin; put behavior in `src/core/*`.

```text
.
├── spec.md
├── README.md
├── AGENTS.md
├── .env.example
├── package.json
├── tsconfig.json
├── next.config.ts
├── eslint.config.mjs
├── vitest.config.ts
├── playwright.config.ts
├── drizzle.config.ts
├── migrations/
├── src/
│   ├── app/
│   │   ├── page.tsx
│   │   ├── layout.tsx
│   │   ├── globals.css
│   │   ├── mock-finance/
│   │   │   └── page.tsx
│   │   └── api/
│   │       ├── agents/route.ts
│   │       ├── observations/route.ts
│   │       ├── retrieve/route.ts
│   │       ├── governance/route.ts
│   │       ├── outcomes/route.ts
│   │       └── demo/reset/route.ts
│   ├── components/
│   │   ├── audit-timeline.tsx
│   │   ├── demo-controls.tsx
│   │   ├── memory-table.tsx
│   │   ├── metric-strip.tsx
│   │   ├── mock-finance-workspace.tsx
│   │   └── reputation-panel.tsx
│   ├── core/
│   │   ├── audit/
│   │   │   └── audit-service.ts
│   │   ├── demo/
│   │   │   ├── demo-fixtures.ts
│   │   │   └── demo-runner.ts
│   │   ├── gemini/
│   │   │   ├── embedding-provider.ts
│   │   │   └── reflection-provider.ts
│   │   ├── governance/
│   │   │   ├── governance-policy.ts
│   │   │   └── governance-service.ts
│   │   ├── memory/
│   │   │   ├── memory-repository.ts
│   │   │   ├── memory-service.ts
│   │   │   └── retrieval-service.ts
│   │   ├── reputation/
│   │   │   └── reputation-service.ts
│   │   ├── schemas.ts
│   │   └── types.ts
│   ├── db/
│   │   ├── client.ts
│   │   ├── schema.ts
│   │   └── seed.ts
│   └── test/
│       └── factories.ts
├── scripts/
│   ├── run-demo-session.ts
│   └── reset-demo-db.ts
└── tests/
    ├── e2e/
    │   └── demo.spec.ts
    ├── integration/
    │   ├── api-flow.test.ts
    │   └── demo-learning-loop.test.ts
    └── unit/
        ├── governance-policy.test.ts
        ├── reputation-service.test.ts
        └── retrieval-service.test.ts
```

---

## Task 1: Scaffold the Typed App and Quality Gates

**Files:**
- Create: `package.json`
- Create: `tsconfig.json`
- Create: `next.config.ts`
- Create: `eslint.config.mjs`
- Create: `vitest.config.ts`
- Create: `playwright.config.ts`
- Create: `.env.example`
- Create: `README.md`
- Create: `AGENTS.md`
- Create: `src/app/layout.tsx`
- Create: `src/app/globals.css`
- Create: `src/app/page.tsx`

**Interfaces:**
- Produces: strict TypeScript project, lint command, typecheck command, unit test command, e2e command.
- Consumes: none.

- [ ] **Step 1: Create the Next.js TypeScript baseline**

Use current Next.js App Router conventions. Route handlers must live in `app/**/route.ts`, and server-only integrations must stay out of client components.

`package.json` scripts:

```json
{
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "lint": "next lint",
    "typecheck": "tsc --noEmit",
    "test": "vitest run",
    "test:watch": "vitest",
    "test:e2e": "playwright test",
    "db:generate": "drizzle-kit generate",
    "db:migrate": "drizzle-kit migrate",
    "db:seed": "tsx src/db/seed.ts",
    "demo:reset": "tsx scripts/reset-demo-db.ts",
    "demo:session": "tsx scripts/run-demo-session.ts"
  }
}
```

- [ ] **Step 2: Configure strict TypeScript**

`tsconfig.json` must enable `strict`, `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`, `noImplicitOverride`, and path alias `@/*` to `src/*`.

- [ ] **Step 3: Add environment documentation**

`.env.example`:

```bash
DATABASE_URL=file:./data/revmem.db
GEMINI_API_KEY=
GEMINI_PROJECT=
GEMINI_LOCATION=
GEMINI_MODE=developer-api
```

- [ ] **Step 4: Create a minimal dashboard shell**

`src/app/page.tsx` should render a static dashboard shell for this task: RevMem, reputation, memories, retrieval quality, audit trail, and demo controls. Task 9 replaces the shell with server-side demo data.

- [ ] **Step 5: Verify gates**

Run:

```bash
npm run lint
npm run typecheck
npm run test
```

Expected: all commands pass. If the scaffold command generates different lint behavior, update the script to the current Next.js-supported lint command after checking Next.js docs through Context7.

- [ ] **Step 6: Commit**

```bash
git add .env.example README.md AGENTS.md package.json tsconfig.json next.config.ts eslint.config.mjs vitest.config.ts playwright.config.ts src/app
git commit -m "chore: scaffold revmem app"
```

---

## Task 2: Add Domain Types, Validation Schemas, and Database Schema

**Files:**
- Create: `src/core/types.ts`
- Create: `src/core/schemas.ts`
- Create: `src/db/schema.ts`
- Create: `src/db/client.ts`
- Create: `drizzle.config.ts`
- Create: `tests/unit/schema-validation.test.ts`

**Interfaces:**
- Produces: `ObservationInput`, `RetrievalRequest`, `GovernanceRequest`, `TaskOutcomeInput`, `MemoryRecord`, `PermissionTier`, Zod schemas, Drizzle tables.
- Consumes: Task 1 project setup.

- [ ] **Step 1: Write validation tests first**

`tests/unit/schema-validation.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { observationInputSchema, retrievalRequestSchema } from "@/core/schemas";

describe("core API schemas", () => {
  it("accepts a valid computer-use observation", () => {
    const parsed = observationInputSchema.parse({
      agentId: "agent-demo",
      sessionId: "session-1",
      taskKind: "fee_leakage_detection",
      source: "computer_use",
      content: "Invoice INV-100 includes a 3% processing fee missing from contract C-100.",
      entities: { invoiceId: "INV-100", contractId: "C-100" },
      occurredAt: "2026-06-27T14:00:00.000Z"
    });

    expect(parsed.entities.invoiceId).toBe("INV-100");
  });

  it("rejects retrieval requests with an unsafe limit", () => {
    expect(() =>
      retrievalRequestSchema.parse({
        agentId: "agent-demo",
        sessionId: "session-1",
        taskKind: "fee_leakage_detection",
        query: "find fee leakage",
        limit: 100
      })
    ).toThrow();
  });
});
```

- [ ] **Step 2: Define union types and interfaces**

Use the core interfaces from the architecture section. Do not use `any`; use `Record<string, string>` for extracted entity maps and explicit union types for enum-like fields.

- [ ] **Step 3: Define Zod schemas**

Implement schemas in `src/core/schemas.ts`. Use `z.record(z.string(), z.string())` for entity maps and constrain retrieval `limit` to `1..12`.

- [ ] **Step 4: Define Drizzle tables**

Implement Drizzle tables matching the storage strategy. Use text IDs generated by the application, integer timestamps or ISO text consistently, and JSON text columns for arrays/vectors in SQLite.

- [ ] **Step 5: Generate the initial migration**

Run:

```bash
npm run db:generate
```

Expected: a migration appears under `migrations/`.

- [ ] **Step 6: Verify**

Run:

```bash
npm run lint
npm run typecheck
npm run test -- schema-validation
```

Expected: all commands pass.

- [ ] **Step 7: Commit**

```bash
git add drizzle.config.ts migrations src/core src/db tests/unit/schema-validation.test.ts
git commit -m "feat: add revmem domain schema"
```

---

## Task 3: Seed Mock Finance Data and Build the Mock Workspace

**Files:**
- Create: `src/core/demo/demo-fixtures.ts`
- Create: `src/db/seed.ts`
- Create: `scripts/reset-demo-db.ts`
- Create: `src/components/mock-finance-workspace.tsx`
- Create: `src/app/mock-finance/page.tsx`
- Create: `tests/integration/seed.test.ts`
- Create: `tests/e2e/demo.spec.ts`

**Interfaces:**
- Produces: deterministic contracts, invoices, pipeline deals, and resettable demo database.
- Consumes: Drizzle schema from Task 2.

- [ ] **Step 1: Write seed test**

`tests/integration/seed.test.ts` should reset an isolated test DB, run the seed function, and assert at least one leakage case:

```ts
expect(invoiceLine.description).toContain("processing fee");
expect(contract.allowedFees).not.toContain("processing fee");
```

- [ ] **Step 2: Create demo fixtures**

Create three customers:

- Acme Manufacturing: invoice includes a fee not allowed by contract.
- Northstar Software: pipeline stage is stale after contract signature.
- Bluebird Logistics: invoice and contract match, used as a control case.

- [ ] **Step 3: Implement reset and seed scripts**

`scripts/reset-demo-db.ts` must clear all tables and call the seed function. Keep this deterministic so the judges can rerun the demo.

- [ ] **Step 4: Build mock finance UI**

`src/components/mock-finance-workspace.tsx` should show contracts, invoices, pipeline deals, and visible record IDs. It should feel like an operational tool, not a landing page.

- [ ] **Step 5: Add Playwright smoke test**

`tests/e2e/demo.spec.ts` should open `/mock-finance` and assert the Acme invoice, contract, and pipeline deal are visible.

- [ ] **Step 6: Verify**

Run:

```bash
npm run db:seed
npm run lint
npm run typecheck
npm run test -- seed
npm run test:e2e
```

Expected: seed is deterministic, UI smoke test passes.

- [ ] **Step 7: Commit**

```bash
git add src/core/demo src/db/seed.ts scripts/reset-demo-db.ts src/components/mock-finance-workspace.tsx src/app/mock-finance tests/integration/seed.test.ts tests/e2e/demo.spec.ts
git commit -m "feat: add mock finance workspace"
```

---

## Task 4: Implement Memory Ingestion and Consolidation

**Files:**
- Create: `src/core/gemini/embedding-provider.ts`
- Create: `src/core/gemini/reflection-provider.ts`
- Create: `src/core/memory/memory-repository.ts`
- Create: `src/core/memory/memory-service.ts`
- Create: `src/core/audit/audit-service.ts`
- Create: `tests/unit/memory-service.test.ts`

**Interfaces:**
- Consumes: `ObservationInput`.
- Produces: `MemoryRecord[]`, `AuditEvent`, `MemoryEdge`.

- [ ] **Step 1: Write memory consolidation tests**

Test that a fee observation creates a `fee_pattern` memory linked to source observation and emits an audit event.

- [ ] **Step 2: Define provider interfaces**

`EmbeddingProvider`:

```ts
export interface EmbeddingProvider {
  embed(text: string): Promise<number[]>;
}
```

`ReflectionProvider`:

```ts
export interface ReflectionProvider {
  summarizeObservation(input: ObservationInput): Promise<{
    kind: MemoryKind;
    title: string;
    body: string;
    tags: string[];
    confidence: number;
  }>;
}
```

- [ ] **Step 3: Implement deterministic local providers**

Create local providers that make tests and offline demos deterministic. The embedding provider should hash tokens into a fixed-length vector. The reflection provider should classify content with explicit finance keywords.

- [ ] **Step 4: Implement Gemini-backed reflection**

Use `@google/genai` server-side. Before coding exact calls, query Context7 for the current SDK method signatures. Keep Gemini behind `ReflectionProvider` so tests use the deterministic provider.

- [ ] **Step 5: Implement memory service**

`MemoryService.ingestObservation(input: ObservationInput): Promise<MemoryRecord[]>` should validate input, persist the raw observation, create or update one memory, create relevant edges, and append audit events.

- [ ] **Step 6: Verify**

Run:

```bash
npm run lint
npm run typecheck
npm run test -- memory-service
```

Expected: memory consolidation tests pass without network access.

- [ ] **Step 7: Commit**

```bash
git add src/core/gemini src/core/memory src/core/audit tests/unit/memory-service.test.ts
git commit -m "feat: add governed memory ingestion"
```

---

## Task 5: Implement Retrieval and Outcome-Based Reranking

**Files:**
- Create: `src/core/memory/retrieval-service.ts`
- Create: `tests/unit/retrieval-service.test.ts`

**Interfaces:**
- Consumes: `RetrievalRequest`, `MemoryRecord[]`, retrieval events, task outcomes.
- Produces: `RetrievalResult[]`.

- [ ] **Step 1: Write ranking tests**

Tests must prove:

- A fee-leakage query ranks `fee_pattern` memories above unrelated pipeline memories.
- A memory marked helpful in a previous outcome ranks higher in the next session.
- Retrieval emits score reasons.

- [ ] **Step 2: Implement ranking components**

Implement pure functions:

```ts
lexicalMatch(query: string, memory: MemoryRecord): number
vectorSimilarity(a: number[], b: number[]): number
taskKindBoost(taskKind: TaskKind, memory: MemoryRecord): number
recencyBoost(updatedAt: string, now: Date): number
```

- [ ] **Step 3: Implement `RetrievalService.retrieve`**

Validate request, embed the query, fetch candidate memories, compute score, persist retrieval event, and return top results with reasons.

- [ ] **Step 4: Implement helpfulness update**

When outcomes mark returned memory IDs as helpful, increment `usefulnessScore` and link the retrieval event to the outcome.

- [ ] **Step 5: Verify**

Run:

```bash
npm run lint
npm run typecheck
npm run test -- retrieval-service
```

Expected: ranking and usefulness tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/core/memory/retrieval-service.ts tests/unit/retrieval-service.test.ts
git commit -m "feat: add self-improving retrieval"
```

---

## Task 6: Implement Reputation and Governance

**Files:**
- Create: `src/core/reputation/reputation-service.ts`
- Create: `src/core/governance/governance-policy.ts`
- Create: `src/core/governance/governance-service.ts`
- Create: `tests/unit/reputation-service.test.ts`
- Create: `tests/unit/governance-policy.test.ts`

**Interfaces:**
- Consumes: `TaskOutcomeInput`, `GovernanceRequest`, current agent reputation.
- Produces: updated reputation, permission tier, `GovernanceDecision`.

- [ ] **Step 1: Write reputation tests**

Test the exact score deltas from the architecture section and tier transitions at 35, 65, and 85.

- [ ] **Step 2: Write governance tests**

Test that a low-reputation agent can read context but cannot update pipeline, while a high-reputation agent can update allowed mock records.

- [ ] **Step 3: Implement scoring**

`ReputationService.recordOutcome(input)` should persist task outcome, add a reputation event, update agent score, and recalculate tier.

- [ ] **Step 4: Implement policy**

`governance-policy.ts` should contain deterministic required-tier mapping:

```ts
const requiredTierByAction = {
  read_context: "observe",
  recommend_change: "recommend",
  update_pipeline: "act_with_approval",
  mark_fee_leakage: "act_with_approval"
} satisfies Record<GovernanceRequest["action"], PermissionTier>;
```

- [ ] **Step 5: Implement governance service**

Persist every allow/deny decision with inputs and explanation. Denied decisions must also create an audit event.

- [ ] **Step 6: Verify**

Run:

```bash
npm run lint
npm run typecheck
npm run test -- reputation-service governance-policy
```

Expected: reputation and governance tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/core/reputation src/core/governance tests/unit/reputation-service.test.ts tests/unit/governance-policy.test.ts
git commit -m "feat: add adaptive governance"
```

---

## Task 7: Expose Thin REST APIs

**Files:**
- Create: `src/app/api/agents/route.ts`
- Create: `src/app/api/observations/route.ts`
- Create: `src/app/api/retrieve/route.ts`
- Create: `src/app/api/governance/route.ts`
- Create: `src/app/api/outcomes/route.ts`
- Create: `src/app/api/demo/reset/route.ts`
- Create: `tests/integration/api-flow.test.ts`

**Interfaces:**
- Consumes: core services from Tasks 4-6.
- Produces: REST contracts that can be wrapped by an MCP server after the hackathon.

- [ ] **Step 1: Write API flow test**

The test should create an agent, post an observation, retrieve context, request governance, record an outcome, and assert reputation changes.

- [ ] **Step 2: Implement route handlers**

Use App Router `route.ts` files. Validate JSON request bodies with Zod. Return `400` for validation errors and `500` only for unexpected failures.

- [ ] **Step 3: Keep routes thin**

Each route handler should do only request parsing, service call, and response formatting. Business rules belong in `src/core/*`.

- [ ] **Step 4: Verify**

Run:

```bash
npm run lint
npm run typecheck
npm run test -- api-flow
```

Expected: full API flow passes.

- [ ] **Step 5: Commit**

```bash
git add src/app/api tests/integration/api-flow.test.ts
git commit -m "feat: expose revmem api"
```

---

## Task 8: Build the Demo Learning Loop

**Files:**
- Create: `src/core/demo/demo-runner.ts`
- Create: `scripts/run-demo-session.ts`
- Create: `tests/integration/demo-learning-loop.test.ts`

**Interfaces:**
- Consumes: REST-equivalent service calls, seeded mock data.
- Produces: repeatable session results showing improvement.

- [ ] **Step 1: Write learning-loop test**

Test that running three sessions improves at least two of:

- helpful retrieval count
- task success count
- reputation score
- permission tier

- [ ] **Step 2: Implement session runner**

`runDemoSession(sessionNumber: 1 | 2 | 3)` should:

1. Create or load `agent-demo`.
2. Use seeded mock data.
3. Post observations.
4. Retrieve context.
5. Request governance decision.
6. Record outcome.
7. Return a summary object for the dashboard and CLI.

- [ ] **Step 3: Add Gemini reflection to the runner**

When `GEMINI_API_KEY` or Vertex/Enterprise env vars are present, use Gemini reflection through the provider interface. When env vars are absent, use deterministic local reflection and clearly label the run as local mode.

- [ ] **Step 4: Add CLI output**

`npm run demo:session -- --session 1` should print session number, retrieved memories, outcome, reputation delta, and permission tier.

- [ ] **Step 5: Verify**

Run:

```bash
npm run demo:reset
npm run demo:session -- --session 1
npm run demo:session -- --session 2
npm run demo:session -- --session 3
npm run lint
npm run typecheck
npm run test -- demo-learning-loop
```

Expected: the three-session flow shows measurable improvement.

- [ ] **Step 6: Commit**

```bash
git add src/core/demo/demo-runner.ts scripts/run-demo-session.ts tests/integration/demo-learning-loop.test.ts
git commit -m "feat: add repeatable learning demo"
```

---

## Task 9: Build the Observability Dashboard

**Files:**
- Create: `src/components/metric-strip.tsx`
- Create: `src/components/reputation-panel.tsx`
- Create: `src/components/memory-table.tsx`
- Create: `src/components/audit-timeline.tsx`
- Create: `src/components/demo-controls.tsx`
- Modify: `src/app/page.tsx`

**Interfaces:**
- Consumes: sessions, memories, retrieval events, reputation events, governance decisions, audit events.
- Produces: first-screen demo dashboard.

- [ ] **Step 1: Add dashboard data loader**

Create server-side data functions that fetch current demo state. Do not fetch from client components unless interaction requires it.

- [ ] **Step 2: Implement metric strip**

Show:

- session count
- current reputation
- permission tier
- helpful retrieval rate
- successful task count

- [ ] **Step 3: Implement panels**

Memory table should show kind, title, usefulness, confidence, and source session. Reputation panel should show score over time. Audit timeline should show observations, retrievals, governance decisions, and outcomes.

- [ ] **Step 4: Implement demo controls**

Buttons should reset demo and run next session by calling local API routes. Keep button labels short and operational.

- [ ] **Step 5: Verify**

Run:

```bash
npm run lint
npm run typecheck
npm run test
npm run test:e2e
```

Expected: dashboard renders populated demo data and e2e smoke still passes.

- [ ] **Step 6: Commit**

```bash
git add src/app/page.tsx src/components
git commit -m "feat: add revmem observability dashboard"
```

---

## Task 10: Add Hackathon Documentation and Demo Script

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`
- Create: `docs/demo-script.md`
- Create: `docs/architecture.md`

**Interfaces:**
- Consumes: implemented app behavior.
- Produces: clear developer setup, judge demo flow, architecture explanation, and agent instructions.

- [ ] **Step 1: Update README**

Include:

- one-line product description
- setup commands
- env vars
- dev server command
- demo reset and session commands
- validation commands
- hackathon scope and explicit non-goals

- [ ] **Step 2: Update AGENTS**

Include project-specific guidance:

- keep core logic in `src/core/*`
- keep route handlers thin
- use deterministic providers in tests
- do not expose Gemini keys to client components
- run lint, typecheck, unit tests, and e2e smoke for demo changes

- [ ] **Step 3: Write demo script**

`docs/demo-script.md` should cover:

1. Open dashboard.
2. Reset demo.
3. Show cold-start agent with low reputation.
4. Run session 1 and show weak context.
5. Run session 2 and show better retrieval.
6. Run session 3 and show expanded governance tier.
7. Open audit timeline and explain why the system is governed.

- [ ] **Step 4: Write architecture doc**

`docs/architecture.md` should summarize the architecture in this plan without implementation checklist detail.

- [ ] **Step 5: Verify**

Run:

```bash
npm run lint
npm run typecheck
npm run test
npm run test:e2e
```

Expected: all gates pass after docs updates.

- [ ] **Step 6: Commit**

```bash
git add README.md AGENTS.md docs/demo-script.md docs/architecture.md
git commit -m "docs: document revmem demo"
```

---

## 48-Hour Execution Schedule

### Day 1 Morning

- Task 1: scaffold and gates.
- Task 2: types and database schema.
- Task 3: seed data and mock finance UI.

### Day 1 Afternoon

- Task 4: memory ingestion.
- Task 5: retrieval and reranking.
- Task 6: reputation and governance.

### Day 2 Morning

- Task 7: REST APIs.
- Task 8: demo learning loop with Gemini reflection adapter.

### Day 2 Afternoon

- Task 9: dashboard.
- Task 10: docs, demo script, final validation.

Cut scope in this order if time gets tight:

1. Remove Playwright e2e beyond one smoke test.
2. Keep graph edges simple with only `derived_from` and `mentions_contract`.
3. Use deterministic embeddings and Gemini reflection only.
4. Skip MCP wrapper entirely.
5. Keep governance actions simulated instead of mutating mock pipeline data.

Do not cut:

- three-session learning loop
- visible reputation change
- visible retrieval improvement
- audit trail
- Gemini-backed reflection path when credentials are available

---

## Self-Review

### Spec Coverage

- Structured finance memory: Tasks 2, 4, and 5.
- Self-improving retrieval: Task 5.
- Agent identity and reputation: Tasks 2 and 6.
- Adaptive governance: Task 6.
- Audit and observability: Tasks 4 and 9.
- Feedback and reflection: Tasks 4 and 8.
- Gemini usage: Tasks 4 and 8.
- Computer Use integration: supported as an observation source and demo runtime boundary in Tasks 4, 7, and 8.
- Stateful improvement across sessions: Task 8.
- Simple dashboard: Task 9.
- Hackathon scope and post-hackathon scaling: architecture sections and Task 10.

### Overengineering Check

This plan intentionally avoids separate services, a dedicated vector database, a graph database, real finance integrations, a full MCP server, production auth, and multi-agent orchestration. The scalable part is the boundary design, not infrastructure sprawl.

### Validation Policy

Every implementation task must run:

```bash
npm run lint
npm run typecheck
```

Every implementation task with behavior must also run the narrow test named in that task. Dashboard/demo changes must run the e2e smoke test.

### Documentation Policy

README and AGENTS updates are deferred until Task 10 because the repo currently only contains `spec.md`; adding project instructions before the architecture exists would be noise. After Task 10, any major architectural change must update `docs/architecture.md`, README setup notes, and AGENTS implementation guidance in the same change.
