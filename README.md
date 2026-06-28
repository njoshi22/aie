# RevMem

SQLite-backed memory engine and FastAPI tool server for the RevMem agent, exposed to the hosted agent via ngrok.

## Run (local + ngrok)

1. `uv run python -m data.seed`
2. `uv run uvicorn api.main:app --host 0.0.0.0 --port 8000`
3. `ngrok http 8000 --domain=<your-reserved>.ngrok.app`
4. Set `REVMEM_BASE_URL` to the ngrok URL for the agent and the UI.

DB persists at `db/revmem.db`. Delete it to reset; `data.seed` reloads policy + CRM.

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
#   REVMEM_BASE_URL=http://localhost:8000
#   REVMEM_STUB_MODE=0
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

### 2. Run the CLI demo (offline scaffold, no API key)

The CLI replays a reconciliation session with mock data and drives the approval gate.

```bash
# Session 1 — cold start (no approval needed)
uv run python -m cli.run --session s1

# Session 3 — scaffold approval flow (default, no Gemini call)
uv run python -m cli.run

# Fast noninteractive scaffold check for local integration runs
uv run python -m cli.run --fast
uv run python -m cli.run --fast --all

# Skip approval polling (just print the link)
uv run python -m cli.run --no-wait
```

Open the approval link printed in the terminal to approve/reject as the routed approver.
`--fast` also skips the demo pacing sleeps; `REVMEM_CLI_FAST=1` enables the same
mode for scripts. Use scaffold mode for quick local integration checks; `--live`
still calls the hosted agent API, so model/network latency remains.
For real approval polling, run the canonical API server and set `REVMEM_BASE_URL`.

### 3. Run the CLI with a real agent (`--live` mode, requires API key)

Same Rich terminal UI, but powered by the real Antigravity agent making real decisions and calling RevMem tools.

`uv run python -m cli.run` is scaffold-only and does not call Gemini.
`uv run python -m cli.run --live` calls Gemini and refuses to run unless
`REVMEM_BASE_URL` points at a running RevMem API. Use `--allow-stub-live`
only for explicit offline diagnostics.

Approval claims in final text are not treated as approval evidence. A compliant live run must either call `route_for_approval` directly or attempt a governed tool such as `write_crm` so the pre-tool-use hook can route approval before execution.

**Terminal 1** — start the RevMem API + ngrok:

```bash
uv run uvicorn api.main:app --port 8000
# In another terminal:
ngrok http 8000 --domain=<your-reserved>.ngrok.app
```

**Terminal 2** — run the live CLI:

```bash
export GEMINI_API_KEY=...
export REVMEM_BASE_URL=https://<your-reserved>.ngrok.app
export REVMEM_STUB_MODE=0

# Single session (default: session 3, ANALYST tier)
uv run python -m cli.run --live
uv run python -m cli.run --live --session 1

# All 3 sessions (1→2→3) with env-ID threading — the full demo narrative
uv run python -m cli.run --live --all
uv run python -m cli.run --live --fast --all

# Self-improvement run
# Seeds once with S1/S2, then runs session 3 ten times on the same agent
uv run python -m cli.run --live --runs 10

# Skip approval polling
uv run python -m cli.run --live --no-wait
```

`--all` runs a clean 3-session demo narrative: cold start → learned →
generalized. It uses a fresh per-run agent by default so old SQLite reputation
does not pollute the story.

`--runs N` is the stateful self-improvement path. It uses one agent, seeds it
once with S1/S2, then runs session 3 exactly N times so the counted trials are
post-learning generalization attempts. Add `--reuse-agent` to continue with the
persisted demo agent across separate CLI invocations; otherwise each invocation
gets a fresh agent identity while still remaining stateful within that run.

Live runs print timing markers so you can tell waiting from a hang:

```text
[->] hosted agent API: initial response
     waiting for model response...
[ok] hosted agent API: initial response
     12.4s
[ok] retrieve_context completed
     1.1s
```

`hosted agent API` is the remote Antigravity/Gemini interaction call. Full live
sessions prefetch RevMem memories before the first model call, so a second
`hosted agent API: after tool results` line should only appear if the model still
chooses to call a tool. `retrieve_context completed` measures RevMem lookup time;
if `GEMINI_API_KEY` is set on the RevMem API server, that lookup may include an
embedding API call. Use `--debug-agent` for the lower-level step list when a run
still looks suspicious.

### 4. Run the agent via Python runner (raw output, requires API key)

```bash
export GEMINI_API_KEY=...

# Single session
uv run python -m agent.runner --session 1

# All 3 sessions sequentially (interactive, pauses between sessions)
uv run python -m agent.demo
```

For the full flow with a live approval gate, also run the canonical API server and expose it:

```bash
# Terminal 1: RevMem API server
uv run uvicorn api.main:app --port 8000

# Terminal 2: ngrok tunnel
ngrok http 8000 --domain=<your-reserved>.ngrok.app

# Terminal 3: agent (set the base URL to your tunnel)
export REVMEM_BASE_URL=https://<your-reserved>.ngrok.app
export REVMEM_STUB_MODE=0
uv run python -m agent.demo
```

### 5. Run the agent via Antigravity CLI (interactive demo)

The Antigravity CLI can drive the same managed agent interactively. It reads the agent persona and skills from `.agents/` on disk, and the agent calls RevMem tools via the ngrok-exposed API — same tool call flow as the Python runner.

**Terminal 1** — start RevMem API + ngrok:

```bash
uv run uvicorn api.main:app --port 8000
# In another terminal:
ngrok http 8000 --domain=<your-reserved>.ngrok.app
```

**Terminal 2** — launch Antigravity CLI:

```bash
export GEMINI_API_KEY=...
export REVMEM_BASE_URL=https://<your-reserved>.ngrok.app
export REVMEM_STUB_MODE=0

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
│   ├── tool_policy.py  # Pre-tool-use approval and write-gate policy
│   ├── tool_types.py   # Shared tool evidence types
│   ├── prompts.py      # System prompts for reconciliation
│   ├── revmem_client.py # HTTP client for RevMem API
│   ├── templates/      # Reads .agents/ files, generates tier-scoped SKILL.md
│   └── data/           # Mock contracts, CRM records, policy
├── api/                # FastAPI app exposing the canonical RevMem contract
├── core/               # SQLite-backed memory, policy, and governance logic
├── data/               # Canonical demo seed data
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
├── requirements.txt
└── .env.example
```

## Key Concepts

- **Reputation tiers**: OBSERVER (0.0–0.3) → ANALYST (0.3–0.6) → AUTONOMOUS (0.6–1.0). Higher reputation = broader permissions.
- **Approval gate**: Pre-tool-use and server-enforced. Before `write_crm` executes, the runner's tool hook checks tier, approval status, and discrepancy policy; if human approval is required, it calls `route_for_approval` and blocks the write until the approval is approved. The FastAPI server remains the final enforcement boundary.
- **Continual learning**: The agent learns from its own mistakes via experiential memories, retrieved by embedding-cosine similarity and reranked by reputation-weighted relevance.

## License

MIT
