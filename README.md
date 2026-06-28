# RevMem

Governed memory + reputation layer for autonomous finance agents. An agent reconciles contract pricing against CRM data, learns from human feedback across sessions, and earns broader autonomy as its reputation improves.

Built on **Gemini Managed Agents (Antigravity)** with a local **FastAPI** governance engine exposed via **ngrok**.

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- A Gemini API key ([aistudio.google.com/api-keys](https://aistudio.google.com/api-keys))
- ngrok (for exposing the local API to the hosted agent)

## Setup

```bash
git clone <repo-url> && cd revmem
uv venv && source .venv/bin/activate
uv pip install -r requirements.txt

cp .env.example .env
# Edit .env:
#   GEMINI_API_KEY=...
#   REVMEM_BASE_URL=http://localhost:8000
#   REVMEM_STUB_MODE=0
```

---

## Running the Demo

### Quick Start: `--continuous`

This is the hero mode: one continuous Antigravity interaction chain with live human correction in the middle.

Approval claims in final text are not treated as approval evidence. A compliant run must either call `route_for_approval` directly or attempt a governed service method such as `write_crm`; the service returns `approval_required` with an `approval_request_id` before any gated side effect runs.

**Terminal 1** - start RevMem API + ngrok:

```bash
uv run python -m data.seed
uv run uvicorn api.main:app --host 0.0.0.0 --port 8000
# In another terminal:
ngrok http 8000 --domain=<your-reserved>.ngrok.app
```

**Terminal 2** - run the continuous demo:

```bash
export GEMINI_API_KEY=...
export REVMEM_BASE_URL=https://<your-reserved>.ngrok.app
export REVMEM_STUB_MODE=0

uv run python -m cli.run --continuous
```

#### What Happens

```text
Step 1: Acme Corp - agent has no prior memories
  -> Agent reconciles contract vs CRM with full data + DOA policy
  -> Agent catches discrepancies but may over-escalate or mis-route
  -> Graded against gold labels

Step 2: Human reviewer feedback
  -> You type what the agent got wrong, or press Enter for a default
  -> Feedback is sent as a new interaction in the same chain
  -> Agent autonomously calls store_memory to persist the lesson

Step 3: Globex Inc - testing generalization
  -> New deal, same agent, same interaction chain
  -> Agent calls retrieve_context and finds the lesson from Step 2
  -> Agent applies the learned rule to a deal it has never seen
  -> Should route correctly and dismiss noise
```

Key talking points:
- All three steps share one `environment_id`, giving true Antigravity state continuity.
- Human correction is real typed input, not hardcoded.
- The agent decides what to store via `store_memory`.
- The lesson generalizes from Acme to unseen Globex deal.
- Reputation expands permissions as accuracy improves.

Default feedback if you press Enter:

> The $0.33 monthly invoice difference is a rounding artifact - per DOA-001, differences under $1 should be auto-dismissed, not escalated. Also, the annual schedule mismatch is a schedule_change and should be routed to the Controller per DOA-003, not the CFO.

### Alternative: `--live --all`

The original scripted flow: three separate sessions with automatic progression. It still works, but uses independent interactions rather than one continuous chain.

```bash
uv run python -m cli.run --live --all
```

### Alternative: Single Live Session

```bash
uv run python -m cli.run --live --session 1   # Acme, no memories
uv run python -m cli.run --live --session 3   # Globex, with memories
```

### Offline Scaffold

No API key is needed.

```bash
uv run python -m cli.run                      # scaffold S3
uv run python -m cli.run --session s1          # scaffold S1
uv run python -m cli.run --fast --all          # fast noninteractive
```

---

## Running Tests

```bash
# All tests
uv run python -m pytest -v

# Just the eval grading tests
uv run python -m pytest evals/test_grade.py -v

# Full eval harness, generates evals/report.json
uv run python -m evals.run
```

---

## Project Structure

```text
├── .agents/            # Antigravity agent config
│   ├── AGENTS.md       # Agent persona + feedback handling rules
│   └── skills/reconciliation/SKILL.md
├── agent/              # Antigravity integration
│   ├── runner.py       # Session executor + send_feedback
│   ├── prompts.py      # Reconciliation and feedback prompt builders
│   ├── scenarios.py    # Deal configs + expected outcomes
│   ├── tools.py        # Tool definitions
│   ├── tool_types.py   # Shared tool evidence types
│   ├── revmem_client.py # HTTP client for RevMem API
│   ├── templates/      # AGENTS.md + tier-scoped SKILL.md generator
│   └── data/           # Mock contracts, CRM records, policy
├── api/                # FastAPI app exposing the canonical RevMem contract
│   └── approval_gate.py # Route/method approval gate helper
├── core/               # SQLite memory, reputation, policy, and governance
│   └── approval_policy.py # Route/method approval requirements and approver graphs
├── data/               # Canonical demo seed data
├── cli/                # Rich terminal UI
│   ├── run.py          # --continuous / --live / scaffold modes
│   └── render.py       # Rich panels
├── evals/              # Continual-learning eval suite
├── docs/adr/           # Architecture decision records
└── requirements.txt
```

## Key Concepts

- **Reputation tiers**: OBSERVER (0.0-0.3) -> ANALYST (0.3-0.6) -> AUTONOMOUS (0.6-1.0). Higher reputation means broader permissions.
- **Approval gate**: Service-enforced at the route/method level. Each side-effect method has an explicit approval policy defining whether approval is required, whether approvers are `any` or `all`, and whether one approval depends on another. Service methods either execute, return `approval_required` with an `approval_request_id`, or reject the request. The runner only displays and records service results.
- **Continual learning**: Human feedback -> agent stores lesson via `store_memory` -> future sessions retrieve via `retrieve_context` -> behavior improves.
- **Continuous interaction chain**: `--continuous` keeps one `environment_id` and chains via `previous_interaction_id`, so the agent's cognitive state evolves within a single Antigravity session.

## License

MIT
