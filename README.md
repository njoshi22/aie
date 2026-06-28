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

### Quick Start: `--continuous` (recommended for demo day)

This is the hero mode. One continuous Antigravity interaction chain with live human correction in the middle.

**Terminal 1** — start RevMem API + ngrok:

```bash
uv run python -m data.seed
uv run uvicorn api.main:app --host 0.0.0.0 --port 8000
# In another terminal:
ngrok http 8000 --domain=<your-reserved>.ngrok.app
```

**Terminal 2** — run the continuous demo:

```bash
export GEMINI_API_KEY=...
export REVMEM_BASE_URL=https://<your-reserved>.ngrok.app
export REVMEM_STUB_MODE=0

uv run python -m cli.run --continuous
```

#### What happens

```
Step 1: Acme Corp — agent has NO prior memories
  → Agent reconciles contract vs CRM with full data + DOA policy
  → Agent catches discrepancies but may over-escalate or mis-route
  → Graded against gold labels

Step 2: Human reviewer feedback
  → YOU type what the agent got wrong (or press Enter for a default)
  → Feedback sent as a new interaction in the same chain
  → Agent autonomously calls store_memory to persist the lesson

Step 3: Globex Inc — testing generalization
  → NEW deal, same agent, same interaction chain
  → Agent calls retrieve_context → finds the lesson from Step 2
  → Agent applies the learned rule to a deal it's never seen
  → Should route correctly and dismiss noise
```

**Key talking points for judges:**
- All 3 steps share **one `environment_id`** — true Antigravity stateful memory
- Human correction is **real typed input**, not hardcoded
- Agent **autonomously** decides what to store via `store_memory` tool call
- Lesson **generalizes** from Acme to unseen Globex deal
- Reputation system expands agent's permissions as accuracy improves

#### Default feedback (if you press Enter)

> The $0.33 monthly invoice difference is a rounding artifact — per DOA-001, differences under $1 should be auto-dismissed, not escalated. Also, the annual schedule mismatch is a schedule_change and should be routed to the Controller per DOA-003, not the CFO.

You can type anything — the agent will interpret it and store what it thinks is important.

---

### Alternative: `--live --all` (scripted 3-session mode)

The original demo flow — three separate sessions with automatic progression. Still works, but uses independent interactions (not a continuous chain).

```bash
uv run python -m cli.run --live --all
```

### Alternative: `--live` single session

```bash
uv run python -m cli.run --live --session 1   # Acme, no memories
uv run python -m cli.run --live --session 3   # Globex, with memories
```

### Offline scaffold (no API key needed)

```bash
uv run python -m cli.run                      # scaffold S3
uv run python -m cli.run --session s1          # scaffold S1
uv run python -m cli.run --fast --all          # fast noninteractive
```

---

## Running Tests

```bash
# All tests (no API key needed)
uv run python -m pytest -v

# Just the eval grading tests
uv run python -m pytest evals/test_grade.py -v

# Full eval harness (generates evals/report.json)
uv run python -m evals.run
```

---

## Project Structure

```
├── .agents/            # Antigravity agent config (source of truth)
│   ├── AGENTS.md       # Agent persona + feedback handling rules
│   └── skills/reconciliation/SKILL.md
├── agent/              # Antigravity integration
│   ├── runner.py       # Session executor + send_feedback (continuous chain)
│   ├── prompts.py      # Prompt builders (reconciliation + feedback)
│   ├── scenarios.py    # Deal configs + expected outcomes
│   ├── tools.py        # Tool definitions (tier-gated)
│   ├── tool_policy.py  # Pre-tool-use approval hook
│   ├── revmem_client.py # HTTP client for RevMem API
│   └── templates/      # AGENTS.md + tier-scoped SKILL.md generator
├── api/                # FastAPI app (canonical RevMem contract)
├── core/               # SQLite memory, reputation, governance
├── data/               # Demo seed data (contracts, CRM, policy)
├── cli/                # Rich terminal UI (the demo's hero)
│   ├── run.py          # --continuous / --live / scaffold modes
│   └── render.py       # Rich panels (diff table, rep bar, routing)
├── evals/              # Continual-learning eval suite
├── docs/adr/           # Architecture decision records
└── requirements.txt
```

## Key Concepts

- **Reputation tiers**: OBSERVER (0.0–0.3) → ANALYST (0.3–0.6) → AUTONOMOUS (0.6–1.0). Higher reputation = broader permissions.
- **Approval gate**: Pre-tool-use hook enforces approval before `write_crm`. Routes to the correct approver per DOA policy.
- **Continual learning**: Human feedback → agent stores lesson via `store_memory` → future sessions retrieve via `retrieve_context` → behavior improves.
- **Continuous interaction chain** (`--continuous`): All interactions share one `environment_id` and chain via `previous_interaction_id`. The agent's cognitive state evolves within a single Antigravity session.

## License

MIT
