# RevMem — Architecture Plan

**Hackathon: 24 hours | 3 people | All vibe coding**

---

## What We're Building

RevMem = Python library + FastAPI server + Streamlit dashboard.

An AI agent (Gemini) does finance tasks (fee leakage detection). RevMem stores what the agent learns between sessions. Each session, the agent performs better because RevMem surfaces relevant context. A dashboard shows the improvement visually.

**Demo story in 60 seconds**: Agent starts dumb → does a task → RevMem stores what worked → next session, agent is smarter → dashboard shows reputation going up, better accuracy, faster completion.

---

## Decisions Made

| Decision | Choice | Why |
|----------|--------|-----|
| Memory store | SQLite + JSON | Simplest. No infra. Works for demo |
| Vector/graph DB | Cut | Too much infra for 24h |
| LLM | Gemini (LLM-agnostic interface) | Team has API key |
| Dashboard | Streamlit | Best for vibe coding, Python-only |
| Computer Use | Stretch goal | Not core to demo |
| Architecture | Python package (not separate API server) | Single app, simpler |
| Deployment | Local only | No deploy headaches |
| Demo format | 5 min live + 1 min recorded video | Pre-run Sessions 1-2, live Session 3 |

---

## Repo Structure

```
revmem/
├── api/                  ← [You] FastAPI server
│   ├── main.py           # app entrypoint, CORS, lifespan
│   └── routes.py         # REST endpoints
├── core/                 ← [You] memory + reputation engine  
│   ├── models.py         # shared Pydantic models (Memory, Session, Agent)
│   ├── memory.py         # store, retrieve, update relevance
│   ├── reputation.py     # score calculation, permission tiers
│   ├── session.py        # session lifecycle management
│   └── database.py       # SQLite setup + queries
├── agent/                ← [Person 2] agent logic
│   ├── agent.py          # Gemini agent runner
│   ├── prompts.py        # system prompts, task templates
│   └── scenarios.py      # demo scenario definitions
├── data/                 ← [Person 2] mock finance data
│   ├── billing.json      # mock billing records
│   ├── contracts.json    # mock contract terms
│   └── seed.py           # load seed data into DB
├── dashboard/            ← [Person 3] visualization
│   ├── app.py            # Streamlit main app
│   └── metrics.py        # scoring calculations, chart data
├── db/                   # SQLite files (gitignored)
├── requirements.txt
├── run.py                # single entrypoint: starts API + opens dashboard
└── README.md
```

---

## Core Data Models

```python
# core/models.py

class Memory(BaseModel):
    id: str                    # uuid
    session_id: str            # which session created it
    agent_id: str              # which agent owns it
    type: str                  # billing_rule | contract_clause | pipeline_event | fee_pattern
    content: str               # natural language description
    metadata: dict             # structured data (amounts, dates, clause refs)
    relevance_score: float     # starts 0.5, adjusted by outcomes (0.0 - 1.0)
    access_count: int          # times retrieved
    created_at: datetime
    last_used_at: datetime | None

class Session(BaseModel):
    id: str                    # uuid
    agent_id: str
    task: str                  # what the agent was asked to do
    status: str                # running | completed | failed
    outcome: dict | None       # structured result (findings, accuracy, etc.)
    memories_used: list[str]   # memory IDs retrieved during session
    memories_created: list[str]# memory IDs created during session
    started_at: datetime
    ended_at: datetime | None

class Agent(BaseModel):
    id: str
    name: str
    reputation_score: float    # 0.0 - 1.0
    total_sessions: int
    successful_sessions: int
    permission_tier: str       # observer | analyst | autonomous
    created_at: datetime

class PermissionTier:
    OBSERVER = "observer"      # 0.0-0.3: read-only, query memory
    ANALYST = "analyst"        # 0.3-0.6: write memories, flag anomalies
    AUTONOMOUS = "autonomous"  # 0.6-1.0: take actions, update pipeline
```

---

## API Interface (Contract Between All 3 People)

```python
# What You build, what Person 2 calls, what Person 3 reads from

# Memory operations
POST   /api/memory              # store a new memory
GET    /api/memory/retrieve     # query memories (type, keywords, limit)
PATCH  /api/memory/{id}/score   # update relevance score

# Session operations  
POST   /api/session             # start a new session
PATCH  /api/session/{id}        # update session (outcome, status)
GET    /api/sessions            # list all sessions

# Agent operations
POST   /api/agent               # register agent
GET    /api/agent/{id}          # get agent + reputation + permissions
GET    /api/agent/{id}/reputation/history  # reputation over time

# Feedback loop
POST   /api/feedback            # log outcome → updates memory scores + reputation
```

---

## Core Python Interface

```python
# For Person 2 to use directly (no HTTP needed, same process)

from core.memory import MemoryStore
from core.reputation import ReputationEngine
from core.session import SessionManager

# Start session
session = session_mgr.start(agent_id="agent-1", task="Find fee leakage in Q2 billing")

# Retrieve relevant context
memories = memory_store.retrieve(
    query="fee discrepancy billing",
    memory_type="fee_pattern",
    limit=5
)
# Returns memories sorted by relevance_score (highest first)

# Store new memory
memory_store.store(
    session_id=session.id,
    agent_id="agent-1",
    type="fee_pattern",
    content="Vendor Acme charges 2.5% processing fee on invoices over $50K, but contract Section 4.2 caps at 2.0%",
    metadata={"vendor": "Acme", "expected_rate": 0.02, "actual_rate": 0.025, "clause": "4.2"}
)

# End session with outcome
session_mgr.complete(
    session_id=session.id,
    outcome={"leakages_found": 3, "total_leakages": 3, "accuracy": 1.0}
)

# This automatically triggers:
# 1. Reputation update (success → score goes up)
# 2. Memory relevance update (used memories get score bump)
# 3. Permission tier recalculation
```

---

## Reputation Algorithm

```
After each session:

  success_rate = agent.successful_sessions / agent.total_sessions
  
  # Weighted score: recent sessions matter more
  reputation = 0.6 * success_rate + 0.3 * recent_accuracy + 0.1 * efficiency_bonus
  
  # Clamp to [0, 1]
  agent.reputation_score = clamp(reputation, 0.0, 1.0)
  
  # Update permission tier
  if reputation < 0.3: tier = OBSERVER
  elif reputation < 0.6: tier = ANALYST  
  else: tier = AUTONOMOUS

Memory relevance update:
  For each memory used in session:
    if session succeeded:
      memory.relevance_score = min(1.0, score + 0.1)
    else:
      memory.relevance_score = max(0.0, score - 0.05)
  
  # Unused memories slowly decay
  For memories not used in 3+ sessions:
    memory.relevance_score *= 0.95
```

---

## Demo Scenario Script

### Session 1: Cold Start (Agent reputation = 0.1, tier = OBSERVER)

**Task**: "Analyze Q2 billing data for fee discrepancies"

Agent behavior:
- No relevant memories → retrieves generic context or nothing
- Slowly works through billing records
- Finds 1 of 3 fee leakages (misses 2)
- Stores 5-6 memories (some useful, some noise)

**Outcome**: `{accuracy: 0.33, leakages_found: 1, total: 3}`
→ Reputation stays low (~0.2)

### Session 2: Learning (Agent reputation = 0.2, tier = OBSERVER)

**Task**: "Analyze Q3 billing data for fee discrepancies"

Agent behavior:
- RevMem surfaces: "compare line-item rates vs contract schedule B" (high relevance)
- Agent faster, more focused
- Finds 2 of 3 leakages
- Stores 2-3 refined memories

**Outcome**: `{accuracy: 0.67, leakages_found: 2, total: 3}`
→ Reputation rises (~0.45), tier upgrades to ANALYST

### Session 3: Competent (Agent reputation = 0.45, tier = ANALYST) — LIVE DEMO

**Task**: "Analyze Q4 billing data and flag pipeline impacts"

Agent behavior:
- RevMem surfaces highly relevant fee patterns from Sessions 1-2
- Agent finds 3 of 3 leakages quickly
- New permission: can now flag pipeline impacts (ANALYST tier)
- Stores refined, high-value memories

**Outcome**: `{accuracy: 1.0, leakages_found: 3, total: 3}`
→ Reputation rises (~0.65), tier upgrades to AUTONOMOUS

### Dashboard shows:
- Reputation chart: 0.1 → 0.2 → 0.45 → 0.65 (line going up)
- Accuracy chart: 33% → 67% → 100%
- Memory quality: noise ratio decreasing
- Permission tier: OBSERVER → ANALYST → AUTONOMOUS

---

## Work Split

### You — Core Engine (hours 0-16)

**Priority order:**
1. `core/models.py` — Pydantic models (30 min)
2. `core/database.py` — SQLite schema + basic CRUD (1h)
3. `core/memory.py` — store + retrieve with relevance sorting (2h)
4. `core/reputation.py` — score calculation + tier mapping (1h)
5. `core/session.py` — session lifecycle + outcome logging (1h)
6. `api/routes.py` — FastAPI endpoints (1h)
7. `api/main.py` — app setup (30 min)
8. Integration testing with Person 2's agent (2h)
9. Bug fixes + polish (remaining time)

### Person 2 — Agent + Data (hours 0-16)

**Priority order:**
1. `data/billing.json` + `data/contracts.json` — mock data from domain knowledge (2h)
2. `agent/prompts.py` — system prompt for fee analysis agent (1h)
3. `agent/agent.py` — Gemini agent that calls RevMem (3h)
4. `agent/scenarios.py` — scripted demo scenarios with expected outcomes (2h)
5. `data/seed.py` — seed DB with initial data (30 min)
6. Demo script writing + narrative (2h)
7. Integration with core engine (2h)

**Needs from finance teammate ASAP:**
- Real fee leakage examples → becomes mock data
- Permission tier names → becomes demo narrative
- Billing rule / contract clause examples → becomes seed memories

### Person 3 — Dashboard + Scoring (hours 0-16)

**Priority order:**
1. `dashboard/app.py` — Streamlit skeleton with 4 panels (2h)
   - Reputation chart (line over time)
   - Accuracy chart (bar per session)
   - Memory table (type, content, relevance score)
   - Session log (task, outcome, tier)
2. `dashboard/metrics.py` — read from SQLite, compute display data (2h)
3. Polish charts + real-time refresh (2h)
4. Relevance scoring refinement (2h)
5. Integration testing (2h)

### Everyone — Last 8 hours

| Hours | Activity |
|-------|----------|
| 16-18 | Full integration: run 3 sessions end-to-end |
| 18-20 | Bug fixes, data tuning, demo rehearsal |
| 20-22 | Record 1-min video, write README |
| 22-24 | Final polish, rehearse live demo, push to public repo |

---

## Timeline Checkpoints

| Hour | Checkpoint | Must Be True |
|------|-----------|-------------|
| 4 | **Skeleton** | Models defined, SQLite works, Streamlit shows empty dashboard, Gemini API call works |
| 8 | **Individual pieces work** | Memory store/retrieve works, agent can analyze mock data, dashboard shows dummy data |
| 12 | **Integration** | Agent calls RevMem, stores memories, dashboard reads from same DB |
| 16 | **Demo flow works** | 3 sessions run end-to-end, dashboard shows improvement |
| 20 | **Polish** | Demo rehearsed, edge cases handled, looks clean |
| 24 | **Ship** | Video recorded, README written, repo public |

---

## Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| Gemini API rate limits / downtime | Cache responses. Pre-run sessions, replay in demo if needed |
| 3 people merge conflicts | Each person owns a directory. Minimal shared files (only `models.py`) |
| Agent doesn't "improve" convincingly | Hardcode session 1 to use NO memory. Session 3 retrieval is natural. Improvement is real but guided |
| Dashboard looks ugly | Streamlit default theme is fine. Don't customize — ship |
| Running out of time | Cut in order: Computer Use → graph relationships → advanced reranking. Core demo = memory + reputation + dashboard |

---

## Tech Stack

```
Python 3.11+
FastAPI          — API server
SQLite           — database (via sqlite3 stdlib)
Pydantic         — data models
google-genai     — Gemini API
Streamlit        — dashboard
uvicorn          — ASGI server
```

---

## Quick Start (for README)

```bash
# Install
pip install -r requirements.txt

# Set API key
export GEMINI_API_KEY=your_key

# Seed mock data
python -m data.seed

# Run everything
python run.py
# → API at http://localhost:8000
# → Dashboard at http://localhost:8501

# Run demo sessions
python -m agent.scenarios
```
