# RevMem Hackathon Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build RevMem, a governed memory and context layer that shows a finance/revops agent improving across repeated sessions through better retrieval, reputation, governance, and audit visibility.

**Architecture:** Use one TypeScript monorepo for the hackathon: TanStack Start owns the dashboard and mock finance UI, Hono owns the API, and shared domain modules own memory, retrieval, governance, reputation, audit, and Gemini adapters. Use Postgres with pgvector from day one so retrieval behaves like the scalable version without adding extra infrastructure beyond one database container.

**Tech Stack:** TanStack Start, Hono, TypeScript strict mode, React, Tailwind, Drizzle ORM, Postgres, pgvector, Vitest, Playwright, `@google/genai`, Zod.

## Global Constraints

- Build for a 48-hour hackathon first; do not introduce queues, Kubernetes, event buses, production identity providers, or more than one API service.
- Keep the demo scalable by using clean module boundaries and adapter interfaces, not by prematurely deploying distributed infrastructure.
- MVP must show structured finance memory, self-improving retrieval, agent identity and reputation, adaptive governance, audit/observability, feedback/reflection, Gemini usage, and visible improvement across 2-3 sessions.
- Store graph relationships in relational Postgres tables for the MVP; do not add a dedicated graph database during the hackathon.
- Store embeddings in a pgvector column and index with HNSW/cosine operations through Drizzle migrations.
- Use Gemini through a server-side adapter only; never expose API keys to client components.
- Computer Use integration should feed observations into RevMem. RevMem should not own browser automation in the first build.
- MCP-style shape is a stretch goal; ship REST routes first with request/response contracts that can be wrapped by MCP later.
- Real financial integrations, on-chain identity, production-grade compliance, and complex multi-agent orchestration are out of scope for the hackathon.

---

## Recommended Architecture

### Approach Options

**Recommended: TanStack Start UI plus Hono API in one TypeScript repo.**
This gets the dashboard, mock UIs, APIs, seed data, and demo loop into one repo while avoiding Next.js. It preserves scale by keeping the core logic in framework-independent `src/core/*` modules and gives the API a clean deployable boundary without dragging in a second language.

**Alternative: FastAPI backend plus React frontend.**
This is fine technically, especially if the backend becomes Python-heavy later. It is the wrong first choice here because Gemini JS, TanStack, Zod schemas, Drizzle, and UI contracts can all share TypeScript types if the API is Hono.

**Alternative: MCP server first.**
This is attractive for agent infrastructure, but it risks spending the hackathon on protocol plumbing instead of the visible continual-learning story. Build REST with MCP-shaped contracts first, then wrap the same core services in MCP after the demo.

### System Boundary

RevMem owns memory, retrieval, reputation, governance, audit, mock data, and demo visibility. Gemini/Computer Use is an external agent runtime that interacts with the mock UI and reports observations, decisions, and outcomes back to RevMem.

```text
Gemini / Computer Use Agent
        |
        | observations, retrieval requests, task outcomes
        v
Hono API
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
Postgres + pgvector + Drizzle
        |
        v
TanStack Start Dashboard + Mock Finance UIs
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

Use Postgres and pgvector immediately. This is not overengineering for this project because vector retrieval is core product behavior, and running one `pgvector` container is cheaper than shipping a throwaway local vector path and migrating it later. Use Drizzle migrations and avoid ORM access from UI components.

- `agents`: identity, credential label, reputation score, permission tier.
- `sessions`: session number, agent ID, task kind, started/completed timestamps.
- `observations`: raw event data and extracted entities.
- `memories`: consolidated memory records and `vector(768)` embedding values.
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

For the first build, vector similarity should use pgvector cosine distance. Gemini embeddings should be used when credentials and the current SDK path are available. Tests and offline demo mode should use deterministic local hash vectors behind the same `EmbeddingProvider` interface, with the same configured dimension as the database column. The Gemini adapter should still be used for reflection and memory consolidation so the prize path remains real.

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

1. Move the Hono API to its own deployable service if the TanStack Start app becomes operationally noisy.
2. Add tenant-scoped auth and policy-backed approvals.
3. Add a dedicated graph store only if graph traversal becomes a bottleneck.
4. Wrap REST routes with an MCP server using the same core services.
5. Add real finance/revops connectors after the mock workflow proves value.
6. Tune pgvector indexes, dimensions, and embedding models with production data.

---

## File Structure

Create the app with this structure. Keep Hono route handlers thin; put behavior in `src/core/*`.

```text
.
├── spec.md
├── README.md
├── AGENTS.md
├── .env.example
├── docker-compose.yml
├── package.json
├── tsconfig.json
├── vite.config.ts
├── eslint.config.mjs
├── vitest.config.ts
├── playwright.config.ts
├── drizzle.config.ts
├── migrations/
├── src/
│   ├── api/
│   │   ├── app.ts
│   │   ├── server.ts
│   │   └── routes/
│   │       ├── agents.ts
│   │       ├── observations.ts
│   │       ├── retrieve.ts
│   │       ├── governance.ts
│   │       ├── outcomes.ts
│   │       └── demo.ts
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
│   ├── routes/
│   │   ├── __root.tsx
│   │   ├── index.tsx
│   │   └── mock-finance.tsx
│   ├── router.tsx
│   ├── routeTree.gen.ts
│   ├── styles.css
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

## Task 1: Scaffold the Typed App, API, Database, and Quality Gates

**Files:**
- Create: `package.json`
- Create: `tsconfig.json`
- Create: `vite.config.ts`
- Create: `eslint.config.mjs`
- Create: `vitest.config.ts`
- Create: `playwright.config.ts`
- Create: `docker-compose.yml`
- Create: `.env.example`
- Create: `README.md`
- Create: `AGENTS.md`
- Create: `src/routes/__root.tsx`
- Create: `src/routes/index.tsx`
- Create: `src/router.tsx`
- Create: `src/styles.css`
- Create: `src/api/app.ts`
- Create: `src/api/server.ts`

**Interfaces:**
- Produces: strict TypeScript project, TanStack Start shell, Hono API shell, Postgres container, lint command, typecheck command, unit test command, e2e command.
- Consumes: none.

- [ ] **Step 1: Create the TanStack Start and Hono TypeScript baseline**

Use current TanStack Start conventions for `src/routes/*` and Hono conventions for `src/api/*`. Keep server-only integrations out of React components.

`package.json` scripts:

```json
{
  "scripts": {
    "dev": "vite dev",
    "dev:api": "tsx watch src/api/server.ts",
    "dev:all": "concurrently \"npm run dev\" \"npm run dev:api\"",
    "build": "vite build",
    "lint": "eslint . --max-warnings=0",
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

- [ ] **Step 3: Add Postgres and pgvector**

`docker-compose.yml` should run a single pgvector-backed Postgres service:

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg16
    ports:
      - "5432:5432"
    environment:
      POSTGRES_USER: revmem
      POSTGRES_PASSWORD: revmem
      POSTGRES_DB: revmem
    volumes:
      - revmem-postgres:/var/lib/postgresql/data

volumes:
  revmem-postgres:
```

- [ ] **Step 4: Add environment documentation**

`.env.example`:

```bash
DATABASE_URL=postgres://revmem:revmem@localhost:5432/revmem
API_BASE_URL=http://localhost:8787
EMBEDDING_DIMENSIONS=768
GEMINI_API_KEY=
GEMINI_PROJECT=
GEMINI_LOCATION=
GEMINI_MODE=developer-api
```

- [ ] **Step 5: Create a minimal dashboard shell and API health route**

`src/routes/index.tsx` should render a static dashboard shell for this task: RevMem, reputation, memories, retrieval quality, audit trail, and demo controls. Task 9 replaces the shell with API-backed demo data.

`src/api/app.ts` should export a Hono app with `GET /healthz` returning JSON:

```json
{ "ok": true, "service": "revmem-api" }
```

- [ ] **Step 6: Verify gates**

Run:

```bash
npm run dev:api
npm run lint
npm run typecheck
npm run test
```

Expected: the API starts, `/healthz` responds, and all commands pass. If TanStack Start or Hono setup syntax differs, check Context7 before changing it.

- [ ] **Step 7: Commit**

```bash
git add .env.example README.md AGENTS.md docker-compose.yml package.json tsconfig.json vite.config.ts eslint.config.mjs vitest.config.ts playwright.config.ts src/routes src/router.tsx src/styles.css src/api
git commit -m "chore: scaffold revmem app and api"
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
- Produces: `ObservationInput`, `RetrievalRequest`, `GovernanceRequest`, `TaskOutcomeInput`, `MemoryRecord`, `PermissionTier`, Zod schemas, Drizzle Postgres tables, pgvector migration.
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

- [ ] **Step 4: Define Drizzle Postgres tables**

Implement Drizzle tables matching the storage strategy. Use text IDs generated by the application, timestamp columns consistently, JSONB columns for structured metadata, and a pgvector `vector` column for embeddings. Create the `vector` extension in the migration before creating the memory embedding index.

- [ ] **Step 5: Generate the initial migration**

Run:

```bash
docker compose up -d postgres
npm run db:generate
```

Expected: a migration appears under `migrations/` and includes the pgvector extension and memory embedding index.

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
- Create: `src/routes/mock-finance.tsx`
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
git add src/core/demo src/db/seed.ts scripts/reset-demo-db.ts src/components/mock-finance-workspace.tsx src/routes/mock-finance.tsx tests/integration/seed.test.ts tests/e2e/demo.spec.ts
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
- Produces: `RetrievalResult[]`, pgvector-backed ranking with explainable score reasons.

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

- [ ] **Step 3: Implement pgvector candidate selection**

Use pgvector cosine distance to fetch the nearest memory candidates before applying the full explainable score. Keep the query behind `MemoryRepository.findNearestByEmbedding(embedding, limit)` so index tuning does not leak into service code.

- [ ] **Step 4: Implement `RetrievalService.retrieve`**

Validate request, embed the query, fetch candidate memories, compute score, persist retrieval event, and return top results with reasons.

- [ ] **Step 5: Implement helpfulness update**

When outcomes mark returned memory IDs as helpful, increment `usefulnessScore` and link the retrieval event to the outcome.

- [ ] **Step 6: Verify**

Run:

```bash
npm run lint
npm run typecheck
npm run test -- retrieval-service
```

Expected: ranking and usefulness tests pass.

- [ ] **Step 7: Commit**

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
- Create: `src/api/routes/agents.ts`
- Create: `src/api/routes/observations.ts`
- Create: `src/api/routes/retrieve.ts`
- Create: `src/api/routes/governance.ts`
- Create: `src/api/routes/outcomes.ts`
- Create: `src/api/routes/demo.ts`
- Modify: `src/api/app.ts`
- Create: `tests/integration/api-flow.test.ts`

**Interfaces:**
- Consumes: core services from Tasks 4-6.
- Produces: REST contracts that can be wrapped by an MCP server after the hackathon.

- [ ] **Step 1: Write API flow test**

The test should create an agent, post an observation, retrieve context, request governance, record an outcome, and assert reputation changes.

- [ ] **Step 2: Implement Hono route modules**

Use separate Hono sub-routers and mount them from `src/api/app.ts`. Validate JSON request bodies with Zod. Return `400` for validation errors and `500` only for unexpected failures.

- [ ] **Step 3: Keep routes thin**

Each Hono handler should do only request parsing, service call, and response formatting. Business rules belong in `src/core/*`.

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
git add src/api tests/integration/api-flow.test.ts
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
- Modify: `src/routes/index.tsx`

**Interfaces:**
- Consumes: sessions, memories, retrieval events, reputation events, governance decisions, audit events.
- Produces: first-screen demo dashboard.

- [ ] **Step 1: Add dashboard data loader**

Create a TanStack route loader that fetches current demo state from the Hono API. Demo control buttons can call the API from the client because they are explicit user actions.

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
git add src/routes/index.tsx src/components
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
- keep Hono route handlers thin
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
