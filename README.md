# RevMem

Governed memory + reputation layer for autonomous finance agents. An agent reconciles contract pricing against CRM data, learns from mistakes across sessions, and earns broader autonomy as its reputation improves.

Built on **Gemini Managed Agents (Antigravity)** with a local **FastAPI** governance engine exposed via **ngrok**.

**Demo story**: Agent gets a signed contract → reconciles against CRM → cold agent over-escalates noise and misses a material ramp → RevMem captures the lesson → next session the agent catches the ramp, ignores the noise → reputation rises, permissions expand → by session three it auto-reconciles low-risk fixes and escalates only judgment calls.

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- A Gemini API key ([aistudio.google.com/api-keys](https://aistudio.google.com/api-keys))
- ngrok (for exposing the local API to the hosted agent)

## Setup

```bash
# Clone and install
git clone <repo-url> && cd revmem
uv venv && source .venv/bin/activate
uv pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env and add your keys:
#   GEMINI_API_KEY=...
#   RESEND_API_KEY=...       (optional — omit for console dry-run)
#   APPROVAL_BASE_URL=http://localhost:8000
```

## Local Testing

### 1. Run the evals (offline, no API key needed)

The eval suite validates the continual-learning loop with modeled agent behaviors — no Gemini calls required.

```bash
# Run the grading unit tests
uv run python -m pytest evals/test_grade.py -v

# Run the full eval harness (generates evals/report.json)
uv run python -m evals.run
```

### 2. Run the CLI demo (scaffold mode, no API key)

The CLI replays a reconciliation session with mock data and drives the CFO approval gate.

**Terminal 1** — start the approval endpoint:
```bash
uv run uvicorn notify.approve:app --port 8000
```

**Terminal 2** — run the CLI transcript:
```bash
# Session 1 — cold start (no approval needed)
uv run python -m cli.run --session s1

# Session 3 — live approval flow (default)
uv run python -m cli.run

# Skip approval polling (just print the link)
uv run python -m cli.run --no-wait
```

Open the approval link printed in the terminal to approve/reject as the CFO.

### 3. Run the CLI with a real agent (`--live` mode, requires API key)

Same Rich terminal UI, but powered by the real Antigravity agent making real decisions and calling RevMem tools.

**Terminal 1** — start the approval endpoint + ngrok:
```bash
uv run uvicorn notify.approve:app --port 8000
# In another terminal:
ngrok http 8000 --domain=<your-reserved>.ngrok.app
```

**Terminal 2** — run the live CLI:
```bash
export GEMINI_API_KEY=...
export REVMEM_BASE_URL=https://<your-reserved>.ngrok.app

# Single session (default: session 3, ANALYST tier)
uv run python -m cli.run --live
uv run python -m cli.run --live --session 1

# All 3 sessions (1→2→3) with env-ID threading — the full demo narrative
uv run python -m cli.run --live --all

# Repeat N times to show long-term self-improvement
# Runs sessions 1→2→3 then cycles session 3, reputation accumulates
uv run python -m cli.run --live --runs 10

# Skip approval polling
uv run python -m cli.run --live --no-wait
```

`--all` runs the 3-session demo narrative (cold start → learned → generalized) with pauses between sessions. `--runs N` repeats to show improvement over many iterations — at the end, a summary table shows the reputation trajectory across all runs.

### 4. Run the agent via Python runner (raw output, requires API key)

```bash
export GEMINI_API_KEY=...

# Single session
uv run python -m agent.runner --session 1

# All 3 sessions sequentially (interactive, pauses between sessions)
uv run python -m agent.demo
```

For the full flow with a live approval gate, also run the approval endpoint and expose it:

```bash
# Terminal 1: approval + API server
uv run uvicorn notify.approve:app --port 8000

# Terminal 2: ngrok tunnel
ngrok http 8000 --domain=<your-reserved>.ngrok.app

# Terminal 3: agent (set the base URL to your tunnel)
export REVMEM_BASE_URL=https://<your-reserved>.ngrok.app
uv run python -m agent.demo
```

### 4. Run the agent via Antigravity CLI (interactive demo)

The Antigravity CLI can drive the same managed agent interactively. It reads the agent persona and skills from `.agents/` on disk, and the agent calls RevMem tools via the ngrok-exposed API — same tool call flow as the Python runner.

**Terminal 1** — start RevMem API + ngrok:
```bash
uv run uvicorn notify.approve:app --port 8000
# In another terminal:
ngrok http 8000 --domain=<your-reserved>.ngrok.app
```

**Terminal 2** — launch Antigravity CLI:
```bash
export GEMINI_API_KEY=...
export REVMEM_BASE_URL=https://<your-reserved>.ngrok.app

# Start an interactive session with the managed agent
antigravity

# The CLI reads .agents/AGENTS.md for the agent persona and
# .agents/skills/reconciliation/SKILL.md for available actions.
# Paste a reconciliation prompt and the agent will call RevMem tools
# (retrieve_context, route_for_approval, etc.) autonomously.
```

**When to use which:**
- **Python runner** (`agent.demo`): reproducible 3-session demo with auto-grading, best for recording or consistent demos
- **Antigravity CLI**: interactive, visually impressive, great for live stage demos where you want to poke at the agent in real time

## Project Structure

```
├── .agents/            # Antigravity CLI agent config (source of truth)
│   ├── AGENTS.md       # Agent persona — read by CLI and Python runner
│   └── skills/reconciliation/SKILL.md  # Base skill definitions
├── agent/              # Antigravity integration
│   ├── runner.py       # Interactions API calls, env-ID threading
│   ├── demo.py         # Run all 3 sessions sequentially
│   ├── scenarios.py    # Acme / Globex deal configs + expected outcomes
│   ├── tools.py        # Tool definitions (tier-gated)
│   ├── prompts.py      # System prompts for reconciliation
│   ├── revmem_client.py # HTTP client for RevMem API
│   ├── templates/      # Reads .agents/ files, generates tier-scoped SKILL.md
│   └── data/           # Mock contracts, CRM records, policy
├── cli/                # Rich terminal agent view (the demo's hero)
│   ├── run.py          # Live transcript driver
│   └── render.py       # Rich renderables (diff table, rep bar, routing)
├── evals/              # Continual-learning eval suite
│   ├── harness.py      # Eval runner
│   ├── behaviors.py    # Modeled agent behaviors per session
│   ├── gold.py         # Gold-standard expected outcomes
│   ├── grade.py        # Grading logic (material caught, false escalations, accuracy)
│   ├── report.py       # CLI report renderer
│   ├── run.py          # Entry point
│   └── test_grade.py   # Unit tests for grading
├── notify/             # Email + approval
│   ├── email.py        # Resend email (+ console dry-run fallback)
│   └── approve.py      # Scaffold approval endpoints (FastAPI)
├── requirements.txt
└── .env.example
```

## Key Concepts

- **Reputation tiers**: OBSERVER (0.0–0.3) → ANALYST (0.3–0.6) → AUTONOMOUS (0.6–1.0). Higher reputation = broader permissions.
- **Approval gate**: Server-enforced — the agent cannot write CRM data without an approved record, regardless of its behavior.
- **Continual learning**: The agent learns from its own mistakes via experiential memories, retrieved by embedding-cosine similarity and reranked by reputation-weighted relevance.

## License

MIT
