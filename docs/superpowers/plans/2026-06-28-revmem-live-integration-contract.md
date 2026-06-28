# RevMem Live Integration Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the live Antigravity agent, FastAPI service, CLI, and evals use one canonical RevMem contract so the live demo can route for approval, observe policy, and execute a gated CRM write without scaffold-only behavior.

**Architecture:** Treat `api.main:app` as the canonical live service and `notify.approve` as scaffold-only. Promote `data/` to the single source of truth for contracts, CRM records, and policy; make `agent/`, `core/`, and `evals/` consume that shape. Keep the agent tool runner thin: it should translate Antigravity function calls into `agent.revmem_client` calls, while `core/governance.py` remains the server-side authority for routing and writes.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, SQLite, google-genai Interactions API, Rich, pytest, ruff, ty.

---

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Category**: bug / tests / docs
- **Planned at**: commit `2adaab7`, 2026-06-28

## Why this matters

The current scaffold tells the right story, but the live path does not implement it. `core` grants `write_crm`, the architecture says the agent polls approval status and writes CRM, but `agent/tools.py` and `agent/runner.py` do not expose or execute that write path. The live docs also tell operators to run `notify.approve`, while the agent client expects the canonical RevMem API. Finally, `core`, `agent`, and `evals` use different field names and policy semantics, so passing tests do not prove the live product works.

## Current state

- `core/governance.py:7-12` declares `write_crm` and `store_memory` for `analyst` and `autonomous`.
- `agent/tools.py:79-86` only returns `retrieve_context`, `store_memory`, and `route_for_approval`; no `write_crm`, `get_approval_status`, `get_contract`, or `get_crm_record`.
- `agent/runner.py:130-157` only executes `retrieve_context`, `store_memory`, and `route_for_approval`.
- `agent/revmem_client.py:32-48` silently falls back to stubs on HTTP errors even when `REVMEM_BASE_URL` is set.
- `README.md:86-101` tells live-mode users to run `uv run uvicorn notify.approve:app --port 8000`, not `api.main:app`.
- `data/contracts.json` uses `annual_schedule`, `tcv`, and `y1_monthly_invoice`; `agent/data/*.json` and `evals/gold.py` use `annual_schedule_usd`, `tcv_usd`, and `y1_monthly_invoice_usd`.
- `data/policy.json` routes `schedule_change` to `cfo`; `agent/data/policy.json` and `evals/test_grade.py` expect schedule changes to route to `controller`.
- `api/routes.py:163-171` returns retrieved memories and policy, but `agent/revmem_client.py:100-110` discards the policy before returning to the runner.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Tests | `uv run pytest` | exit 0, all tests pass |
| Focused API tests | `uv run pytest tests/test_api.py tests/test_approval.py tests/test_governance.py -v` | exit 0 |
| Focused agent/eval tests | `uv run pytest tests/test_revmem_client.py tests/test_agent_tools.py tests/test_agent_runner.py evals/test_grade.py -v` | exit 0 |
| Lint edited files | `uv run ruff check agent/revmem_client.py agent/tools.py agent/runner.py agent/prompts.py cli/run.py core/governance.py core/models.py data/seed.py evals/gold.py tests/test_revmem_client.py tests/test_agent_tools.py tests/test_agent_runner.py tests/test_api.py tests/test_governance.py tests/test_approval.py` | exit 0 |
| Type-check edited files | `uv run ty check agent/revmem_client.py agent/tools.py agent/runner.py agent/prompts.py cli/run.py core/governance.py core/models.py data/seed.py evals/gold.py tests/test_revmem_client.py tests/test_agent_tools.py tests/test_agent_runner.py tests/test_api.py tests/test_governance.py tests/test_approval.py` | exit 0 |

Note: `uv run pyright` was unavailable at planning time. Use `ty` for type validation unless the repo adds pyright.

## Scope

**In scope:**

- `agent/revmem_client.py`
- `agent/tools.py`
- `agent/runner.py`
- `agent/prompts.py`
- `cli/run.py`
- `core/models.py`
- `core/governance.py`
- `api/routes.py`
- `data/contracts.json`
- `data/salesforce.json`
- `data/policy.json`
- `data/seed.py`
- `evals/gold.py`
- `evals/behaviors.py` if field names need adjustment
- `tests/test_revmem_client.py` (create)
- `tests/test_agent_tools.py` (create)
- `tests/test_agent_runner.py` (create)
- Existing tests under `tests/` and `evals/test_grade.py` as needed
- `README.md`
- `.env.example`

**Out of scope:**

- Replacing SQLite with Postgres or pgvector.
- Rewriting the project into the TypeScript plan in `docs/superpowers/plans/2026-06-27-revmem-hackathon.md`.
- Making production auth. The goal here is contract correctness, not production hardening.
- Deleting `notify/approve.py`. Leave it available for scaffold mode.
- Changing `.agents/AGENTS.md` output schema unless required by field-name unification.

## Git workflow

- Create a branch such as `fix/revmem-live-contract`.
- Commit per task or per two tightly related tasks.
- Use existing conventional style from history, for example `fix: wire live revmem api contract`.
- Do not push, merge, or delete branches unless the operator asks.

## Steps

### Task 1: Make the live client fail closed and document the canonical service

**Files:**
- Modify: `agent/revmem_client.py`
- Modify: `README.md`
- Modify: `.env.example`
- Create: `tests/test_revmem_client.py`

- [ ] **Step 1: Write failing tests for explicit stub mode and live failure behavior**

Create `tests/test_revmem_client.py`:

```python
from __future__ import annotations

import importlib
import urllib.error

import pytest


def _reload_client(monkeypatch, base_url: str | None, stub_mode: str | None = None):
    if base_url is None:
        monkeypatch.delenv("REVMEM_BASE_URL", raising=False)
        monkeypatch.delenv("REVMEM_API_URL", raising=False)
    else:
        monkeypatch.setenv("REVMEM_BASE_URL", base_url)
    if stub_mode is None:
        monkeypatch.delenv("REVMEM_STUB_MODE", raising=False)
    else:
        monkeypatch.setenv("REVMEM_STUB_MODE", stub_mode)
    import agent.revmem_client as client
    return importlib.reload(client)


def test_live_http_error_does_not_fall_back_to_stub(monkeypatch):
    client = _reload_client(monkeypatch, "https://example.ngrok.app")

    def fail(*args, **kwargs):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(client.urllib.request, "urlopen", fail)

    with pytest.raises(client.RevMemApiError):
        client.ensure_agent("RevOps Finance Agent")


def test_stub_mode_must_be_explicit_when_base_url_is_set(monkeypatch):
    client = _reload_client(monkeypatch, "https://example.ngrok.app", "1")

    assert client.ensure_agent("RevOps Finance Agent")["id"] == "revops-agent-1"


def test_no_base_url_defaults_to_stub_mode(monkeypatch):
    client = _reload_client(monkeypatch, None)

    assert client.start_session("a1", "reconcile")["status"] == "running"
```

- [ ] **Step 2: Run the failing test**

Run: `uv run pytest tests/test_revmem_client.py -v`

Expected: FAIL because `RevMemApiError` does not exist and live HTTP errors currently fall back to stubs.

- [ ] **Step 3: Implement explicit stub mode and typed API errors**

In `agent/revmem_client.py`:

- Add `from typing import Any, Mapping, cast`.
- Define `JsonObject = dict[str, Any]` and `JsonValue = JsonObject | list[Any]`.
- Add:

```python
class RevMemApiError(RuntimeError):
    pass
```

- Replace global mode detection with:

```python
REVMEM_BASE_URL = os.environ.get("REVMEM_BASE_URL", os.environ.get("REVMEM_API_URL", "")).rstrip("/")
STUB_MODE = os.environ.get("REVMEM_STUB_MODE") == "1" or not REVMEM_BASE_URL
```

- Change `_api_call` so HTTP and URL errors raise when `STUB_MODE` is false:

```python
def _api_call(method: str, path: str, body: JsonObject | None = None) -> JsonValue:
    if STUB_MODE:
        return _stub_response(method, path, body)

    url = f"{REVMEM_BASE_URL}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=_HEADERS, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raise RevMemApiError(f"{method} {path} failed: {e.code} {e.reason}") from e
    except urllib.error.URLError as e:
        raise RevMemApiError(f"{method} {path} failed: {e.reason}") from e
```

- Add helper functions so public methods can return `dict[str, Any]` without unsafe unions:

```python
def _expect_object(value: JsonValue, path: str) -> JsonObject:
    if isinstance(value, dict):
        return value
    raise RevMemApiError(f"{path} returned a list, expected object")


def _expect_list(value: JsonValue, path: str) -> list[Any]:
    if isinstance(value, list):
        return value
    raise RevMemApiError(f"{path} returned an object, expected list")
```

- Update every public wrapper returning a dict to call `_expect_object`.
- Update the `route_for_approval` docstring to say the canonical API returns no token and no approval link to the agent.

- [ ] **Step 4: Verify client tests pass**

Run: `uv run pytest tests/test_revmem_client.py -v`

Expected: PASS.

- [ ] **Step 5: Fix live docs and environment example**

In `README.md`, change live mode instructions to start the canonical API:

```bash
uv run python -m data.seed
uv run uvicorn api.main:app --host 0.0.0.0 --port 8000
ngrok http 8000 --domain=<your-reserved>.ngrok.app
```

Keep `notify.approve:app` only in scaffold-mode instructions. Add a short note that live approval links are printed by the FastAPI process because the token is not returned to the agent.

In `.env.example`, add:

```bash
REVMEM_BASE_URL=http://localhost:8000
REVMEM_STUB_MODE=0
GEMINI_API_KEY=
```

Leave `APPROVAL_BASE_URL` documented as scaffold-only.

- [ ] **Step 6: Verify docs and client task**

Run:

```bash
uv run pytest tests/test_revmem_client.py -v
uv run ruff check agent/revmem_client.py tests/test_revmem_client.py
uv run ty check agent/revmem_client.py tests/test_revmem_client.py
```

Expected: all commands exit 0.

### Task 2: Canonicalize finance fixtures and policy across core, agent, and evals

**Files:**
- Modify: `data/contracts.json`
- Modify: `data/salesforce.json`
- Modify: `data/policy.json`
- Modify: `data/seed.py`
- Modify: `core/models.py`
- Modify: `core/governance.py`
- Modify: `api/routes.py` if response assumptions change
- Modify: `evals/gold.py`
- Modify: `evals/behaviors.py` only if field names drift
- Modify: `tests/test_api.py`
- Modify: `tests/test_governance.py`
- Modify: `tests/test_seed.py`
- Modify: `evals/test_grade.py`

- [ ] **Step 1: Write or update tests that pin the canonical schema**

Update `tests/test_seed.py` to expect `_usd` field names from the API seed data:

```python
def test_seed_is_idempotent(conn):
    a1 = seed.seed(conn)
    a2 = seed.seed(conn)
    assert a1.id == a2.id
    assert len(database.list_policy(conn)) == 5
    assert database.get_crm(conn, "acme")["annual_schedule_usd"] == [150000, 150000, 150000]


def test_load_contract():
    c = seed.load_contract("acme")
    assert c is not None
    assert c["annual_schedule_usd"] == [100000, 150000, 200000]
    assert seed.load_contract("nope") is None
```

Update `tests/test_api.py`:

```python
def test_contracts_and_crm_served(client):
    assert client.get("/contracts/acme").json()["annual_schedule_usd"] == [100000, 150000, 200000]
    assert client.get("/crm/acme").json()["annual_schedule_usd"] == [150000, 150000, 150000]
```

Update `tests/test_governance.py` so schedule changes route to `controller` and discount-over-authority routes to `cfo_cco`.

- [ ] **Step 2: Run tests to verify the mismatch fails**

Run: `uv run pytest tests/test_seed.py tests/test_api.py tests/test_governance.py evals/test_grade.py -v`

Expected: FAIL on field names and/or schedule routing before implementation.

- [ ] **Step 3: Promote `data/` to the canonical fixture format**

Update `data/contracts.json` and `data/salesforce.json` to use these field names:

- `tcv_usd`
- `term_years`
- `annual_schedule_usd`
- `y1_monthly_invoice_usd`

Keep deal keys as `acme` and `globex`.

Update `data/policy.json` to match the current `agent/data/policy.json` shape:

```json
{
  "name": "Delegation of Authority - Contract Reconciliation",
  "version": 1,
  "rules": [
    {
      "id": "DOA-001",
      "description": "Immaterial rounding differences",
      "condition": {"max_diff_usd": 1},
      "action": "auto_dismiss",
      "route_to": null
    },
    {
      "id": "DOA-002",
      "description": "Minor corrections under $1K",
      "condition": {"min_diff_usd": 1, "max_diff_usd": 1000},
      "action": "auto_resolve",
      "route_to": "am"
    },
    {
      "id": "DOA-003",
      "description": "Moderate discrepancies or schedule changes",
      "condition": {"min_diff_usd": 1000, "max_diff_usd": 50000, "change_types": ["schedule_change", "term_change"]},
      "action": "escalate",
      "route_to": "controller"
    },
    {
      "id": "DOA-004",
      "description": "Large discrepancies over $50K",
      "condition": {"min_diff_usd": 50000},
      "action": "escalate",
      "route_to": "cfo"
    },
    {
      "id": "DOA-005",
      "description": "Discount exceeds deal desk authority (max 20%)",
      "condition": {"change_types": ["discount_over_authority"]},
      "action": "escalate",
      "route_to": "cfo_cco"
    }
  ]
}
```

- [ ] **Step 4: Update policy model and seed loader**

In `core/models.py`, extend `PolicyRule`:

```python
class PolicyRule(BaseModel):
    id: str = Field(default_factory=_uuid)
    description: str
    condition: dict[str, Any]
    route_to: str | None
    action: str = "escalate"
    version: int = 1
```

In `core/database.py`, update `policy_rules` schema and CRUD to persist `action`. If the table already exists without `action`, add an idempotent migration in `init_db`:

```python
def _ensure_policy_action_column(conn: sqlite3.Connection) -> None:
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(policy_rules)").fetchall()}
    if "action" not in cols:
        conn.execute("ALTER TABLE policy_rules ADD COLUMN action TEXT DEFAULT 'escalate'")
        conn.commit()
```

Call it after `conn.executescript(SCHEMA)`.

In `data/seed.py`, load rules from either a top-level list or `{"rules": [...]}` so older local data does not hard-crash:

```python
raw_policy = _load("policy.json")
rules = raw_policy["rules"] if isinstance(raw_policy, dict) else raw_policy
for raw in rules:
    database.upsert_policy(conn, PolicyRule(**raw))
```

- [ ] **Step 5: Update governance route semantics**

In `core/governance.py`, support the canonical policy condition names:

```python
def _numeric_ok(cond: dict[str, Any], amount: float) -> bool:
    min_value = cond.get("min_diff_usd", cond.get("min_usd", 0))
    max_value = cond.get("max_diff_usd", cond.get("max_usd"))
    if amount < float(min_value or 0):
        return False
    if max_value is not None and amount > float(max_value):
        return False
    return True
```

Then make `route` a two-pass waterfall:

1. Matching `change_types` rules.
2. Numeric-only rules.

Return `r.route_to or "none"` for dismiss actions only if a route is required by callers; otherwise keep `route_for_approval` responsible for only material discrepancies.

- [ ] **Step 6: Update evals to read canonical `data/`**

In `evals/gold.py`, change `DATA_DIR` to the repo `data/` directory and load `contracts.json`, `salesforce.json`, and `policy.json` by deal key. Do not read from `agent/data`.

Keep the expected routes:

- Acme `annual_schedule_usd` -> `controller`
- Globex `discount_pct` -> `cfo_cco`

- [ ] **Step 7: Verify canonical fixture tests**

Run:

```bash
uv run pytest tests/test_seed.py tests/test_api.py tests/test_governance.py evals/test_grade.py -v
uv run ruff check core/models.py core/database.py core/governance.py data/seed.py evals/gold.py tests/test_seed.py tests/test_api.py tests/test_governance.py evals/test_grade.py
uv run ty check core/models.py core/database.py core/governance.py data/seed.py evals/gold.py tests/test_seed.py tests/test_api.py tests/test_governance.py evals/test_grade.py
```

Expected: all commands exit 0.

### Task 3: Return active policy to the live agent instead of discarding it

**Files:**
- Modify: `agent/revmem_client.py`
- Modify: `agent/runner.py`
- Modify: `agent/prompts.py`
- Create or modify: `tests/test_agent_runner.py`

- [ ] **Step 1: Write a failing test for retrieve_context policy propagation**

In `tests/test_agent_runner.py`:

```python
from __future__ import annotations

from agent.runner import _execute_tool


def test_retrieve_context_returns_policy_to_agent(monkeypatch):
    def fake_retrieve(agent_id: str, query: str, memory_type: str | None = None, limit: int = 5):
        return {
            "memories": [{"id": "m1", "content": "check annual schedule"}],
            "policy": [{"id": "DOA-003", "route_to": "controller"}],
        }

    monkeypatch.setattr("agent.revmem_client.retrieve_context", fake_retrieve)

    out = _execute_tool("retrieve_context", {"query": "ramp"}, "agent-1", "session-1")

    assert out["count"] == 1
    assert out["memories"][0]["content"] == "check annual schedule"
    assert out["policy"][0]["route_to"] == "controller"
```

- [ ] **Step 2: Run the failing test**

Run: `uv run pytest tests/test_agent_runner.py::test_retrieve_context_returns_policy_to_agent -v`

Expected: FAIL because `revmem_client.retrieve_context` currently returns only the memory list and the runner returns no policy.

- [ ] **Step 3: Preserve retrieve response shape**

In `agent/revmem_client.py`, change `retrieve_context` to return a dict:

```python
def retrieve_context(
    agent_id: str, query: str, memory_type: str | None = None, limit: int = 5
) -> dict[str, Any]:
    params = {"agent_id": agent_id, "query": query, "limit": limit}
    if memory_type:
        params["type"] = memory_type
    result = _api_call("GET", f"/memory/retrieve?{urlencode(params)}")
    if isinstance(result, list):
        return {"memories": result, "policy": []}
    return result
```

Update callers to use `bundle["memories"]`.

- [ ] **Step 4: Update runner to pass policy into the function result**

In `agent/runner.py`, update `_execute_tool`:

```python
if name == "retrieve_context":
    bundle = revmem_client.retrieve_context(agent_id, arguments.get("query", ""))
    memories = bundle.get("memories", [])
    return {"memories": memories, "policy": bundle.get("policy", []), "count": len(memories)}
```

Update `listener.on_memory_retrieved` call sites to use the `memories` list from this result.

- [ ] **Step 5: Update prompt instructions**

In `agent/prompts.py`, replace the instruction that relies on static policy with:

```python
"1. First, call retrieve_context. Use both returned memories and returned policy rules.\n"
"2. Compare every pricing field between the contract and CRM record.\n"
"3. For material discrepancies, call route_for_approval with the exact discrepancy.\n"
```

Do not embed stale policy into the prompt if the retrieved policy is available. It is acceptable to keep the local policy in the environment as a fallback reference, but the prompt must tell the model that `retrieve_context` is authoritative for current policy.

- [ ] **Step 6: Verify policy propagation**

Run:

```bash
uv run pytest tests/test_agent_runner.py::test_retrieve_context_returns_policy_to_agent -v
uv run ruff check agent/revmem_client.py agent/runner.py agent/prompts.py tests/test_agent_runner.py
uv run ty check agent/revmem_client.py agent/runner.py agent/prompts.py tests/test_agent_runner.py
```

Expected: all commands exit 0.

### Task 4: Expose route, poll, and write tools in the live agent

**Files:**
- Modify: `agent/tools.py`
- Modify: `agent/runner.py`
- Modify: `agent/prompts.py`
- Modify: `cli/run.py`
- Create or modify: `tests/test_agent_tools.py`
- Modify: `tests/test_agent_runner.py`

- [ ] **Step 1: Write failing tests for tool exposure**

Create `tests/test_agent_tools.py`:

```python
from __future__ import annotations

from agent.tools import get_tools_for_tier


def _names(tier: str) -> set[str]:
    return {tool["name"] for tool in get_tools_for_tier(tier)}


def test_observer_tools_are_read_and_route_only():
    names = _names("observer")
    assert {"get_contract", "get_crm_record", "retrieve_context", "route_for_approval"} <= names
    assert "write_crm" not in names
    assert "store_memory" not in names


def test_analyst_can_poll_and_write_after_approval():
    names = _names("analyst")
    assert {"get_approval_status", "write_crm", "store_memory"} <= names


def test_autonomous_has_same_write_surface_as_analyst():
    names = _names("autonomous")
    assert {"get_approval_status", "write_crm", "store_memory"} <= names
```

Add `tests/test_agent_runner.py` coverage:

```python
def test_write_crm_tool_executes_client_call(monkeypatch):
    calls = []

    def fake_write(agent_id, deal_id, fields, discrepancy=None, approval_id=None):
        calls.append((agent_id, deal_id, fields, discrepancy, approval_id))
        return {"ok": True, "decision": "allow", "crm": fields}

    monkeypatch.setattr("agent.revmem_client.write_crm", fake_write)

    out = _execute_tool(
        "write_crm",
        {
            "deal_id": "globex",
            "fields": {"annual_schedule_usd": [80000, 120000, 160000]},
            "discrepancy": {"deal_id": "globex", "amount_usd": 40000, "change_type": "schedule_change"},
            "approval_id": "appr-1",
        },
        "agent-1",
        "session-1",
    )

    assert out["ok"] is True
    assert calls[0][0] == "agent-1"
    assert calls[0][1] == "globex"


def test_get_approval_status_tool_executes_client_call(monkeypatch):
    monkeypatch.setattr(
        "agent.revmem_client.get_approval_status",
        lambda approval_id: {"id": approval_id, "status": "approved"},
    )

    out = _execute_tool("get_approval_status", {"approval_id": "appr-1"}, "agent-1", "session-1")

    assert out == {"id": "appr-1", "status": "approved"}
```

- [ ] **Step 2: Run failing tests**

Run: `uv run pytest tests/test_agent_tools.py tests/test_agent_runner.py -v`

Expected: FAIL because the tools and `_execute_tool` branches do not exist yet.

- [ ] **Step 3: Add missing tool declarations**

In `agent/tools.py`, add function declarations for:

- `get_contract(deal_id)`
- `get_crm_record(deal_id)`
- `get_approval_status(approval_id)`
- `write_crm(deal_id, fields, discrepancy, approval_id)`

Use the existing dictionary style. For `write_crm`, make `fields` and `discrepancy` JSON objects:

```python
WRITE_CRM = {
    "type": "function",
    "name": "write_crm",
    "description": "Write approved CRM corrections. Requires ANALYST or AUTONOMOUS tier and a server-approved approval_id unless the server allows autonomous self-reconcile.",
    "parameters": {
        "type": "object",
        "properties": {
            "deal_id": {"type": "string"},
            "fields": {"type": "object"},
            "discrepancy": {"type": "object"},
            "approval_id": {"type": "string"},
        },
        "required": ["deal_id", "fields", "discrepancy"],
    },
}
```

Then return:

- observer: read tools, `retrieve_context`, `route_for_approval`
- analyst: observer tools plus `get_approval_status`, `write_crm`, `store_memory`
- autonomous: same as analyst for this implementation

- [ ] **Step 4: Execute the missing tool branches**

In `agent/runner.py`, add `_execute_tool` branches:

```python
if name == "get_contract":
    return revmem_client.get_contract(arguments.get("deal_id", ""))

if name == "get_crm_record":
    return revmem_client.get_crm_record(arguments.get("deal_id", ""))

if name == "get_approval_status":
    return revmem_client.get_approval_status(arguments.get("approval_id", ""))

if name == "write_crm":
    return revmem_client.write_crm(
        agent_id=agent_id,
        deal_id=arguments.get("deal_id", ""),
        fields=arguments.get("fields", {}),
        discrepancy=arguments.get("discrepancy", {}),
        approval_id=arguments.get("approval_id"),
    )
```

Increase `max_tool_rounds` from 3 to 8 so route, poll, and write can complete in one interaction chain.

- [ ] **Step 5: Update prompt to require the route/poll/write sequence**

In `agent/prompts.py`, add explicit instructions for ANALYST/AUTONOMOUS:

```python
"For material discrepancies, call route_for_approval first. If you receive an approval_id, call get_approval_status with that id. If status is approved and your tier allows writes, call write_crm with the exact approved discrepancy and corrected fields. If status is pending or rejected, do not write.\n"
```

Do not tell OBSERVER to write.

- [ ] **Step 6: Fix live CLI approval polling**

In `cli/run.py`, stop using `notify.approve.wait_for_approval` in `RichListener.on_approval_needed` for live mode. Add a small helper that polls the canonical API:

```python
def wait_for_revmem_approval(approval_id: str, timeout: float = 300.0, interval: float = 2.0) -> dict:
    from agent import revmem_client

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = revmem_client.get_approval_status(approval_id)
        if status.get("status") != "pending":
            return status
        time.sleep(interval)
    raise TimeoutError(f"approval {approval_id} not decided within {timeout:.0f}s")
```

Use this helper in `RichListener`. If the canonical API response has no `approval_link`, print a line that says the human approval link is in the API server logs. Do not request or display the approval token from the agent-facing API.

- [ ] **Step 7: Verify tool exposure and execution tests**

Run:

```bash
uv run pytest tests/test_agent_tools.py tests/test_agent_runner.py -v
uv run ruff check agent/tools.py agent/runner.py agent/prompts.py cli/run.py tests/test_agent_tools.py tests/test_agent_runner.py
uv run ty check agent/tools.py agent/runner.py agent/prompts.py cli/run.py tests/test_agent_tools.py tests/test_agent_runner.py
```

Expected: all commands exit 0.

### Task 5: Add an end-to-end contract regression across API and agent client

**Files:**
- Modify: `tests/test_api.py`
- Modify: `tests/test_approval.py`
- Modify: `tests/test_revmem_client.py`
- Modify: `agent/runner.py` if result shape needs `agent_id`
- Modify: `cli/run.py` if reputation display needs the correct agent id

- [ ] **Step 1: Add API regression for the canonical approval/write flow**

In `tests/test_approval.py`, keep the existing test but update corrected field names:

```python
body = {
    "agent_id": aid,
    "deal_id": "acme",
    "fields": {"annual_schedule_usd": [100000, 150000, 200000]},
    "discrepancy": disc,
    "approval_id": approval_id,
}
```

Assert the CRM response contains `annual_schedule_usd`.

- [ ] **Step 2: Add agent client contract regression**

In `tests/test_revmem_client.py`, add a test for route status and write wrapper shape by monkeypatching `_api_call`:

```python
def test_client_route_status_write_shapes(monkeypatch):
    client = _reload_client(monkeypatch, None)
    calls = []

    def fake_api(method, path, body=None):
        calls.append((method, path, body))
        if path == "/route_for_approval":
            return {"approval_id": "appr-1", "route_to": "controller", "status": "pending"}
        if path == "/approvals/appr-1/status":
            return {"id": "appr-1", "status": "approved"}
        if path == "/crm/write":
            return {"ok": True, "decision": "allow", "crm": body["fields"]}
        raise AssertionError(path)

    monkeypatch.setattr(client, "_api_call", fake_api)

    routed = client.route_for_approval("acme", 40000, "schedule_change")
    status = client.get_approval_status(routed["approval_id"])
    written = client.write_crm(
        "agent-1",
        "acme",
        {"annual_schedule_usd": [100000, 150000, 200000]},
        {"deal_id": "acme", "amount_usd": 40000, "change_type": "schedule_change"},
        "appr-1",
    )

    assert status["status"] == "approved"
    assert written["ok"] is True
```

- [ ] **Step 3: Fix agent result identity**

In `agent/runner.py`, include `agent_id` in `result`:

```python
"agent_id": agent_id,
```

In `cli/run.py`, change `RichListener.on_session_end` to call:

```python
updated = revmem_client.get_agent(result.get("agent_id", ""))
```

Do not use `session_id` to fetch an agent.

- [ ] **Step 4: Verify focused integration tests**

Run:

```bash
uv run pytest tests/test_api.py tests/test_approval.py tests/test_revmem_client.py tests/test_agent_tools.py tests/test_agent_runner.py evals/test_grade.py -v
```

Expected: all selected tests pass.

### Task 6: Final lint, type validation, and docs check

**Files:**
- No new behavior files unless previous tasks exposed a narrowly scoped lint/type issue in an edited file.

- [ ] **Step 1: Run full tests**

Run: `uv run pytest`

Expected: all tests pass.

- [ ] **Step 2: Run ruff on edited files**

Run:

```bash
uv run ruff check agent/revmem_client.py agent/tools.py agent/runner.py agent/prompts.py cli/run.py core/models.py core/database.py core/governance.py api/routes.py data/seed.py evals/gold.py tests/test_revmem_client.py tests/test_agent_tools.py tests/test_agent_runner.py tests/test_api.py tests/test_governance.py tests/test_approval.py tests/test_seed.py evals/test_grade.py
```

Expected: exit 0.

Fix the existing ruff issues in edited files:

- remove unused `dataclass` and `field` imports from `agent/runner.py`
- remove unused `store` import from `cli/run.py`
- remove or use unused `disc_r` in `evals/gold.py`

- [ ] **Step 3: Run type validation on edited files**

Run:

```bash
uv run ty check agent/revmem_client.py agent/tools.py agent/runner.py agent/prompts.py cli/run.py core/models.py core/database.py core/governance.py api/routes.py data/seed.py evals/gold.py tests/test_revmem_client.py tests/test_agent_tools.py tests/test_agent_runner.py tests/test_api.py tests/test_governance.py tests/test_approval.py tests/test_seed.py evals/test_grade.py
```

Expected: exit 0.

If this fails on an edited file, fix the type issue. If it fails only because of pre-existing diagnostics in untouched files, report the exact file and diagnostic count before broadening scope.

- [ ] **Step 4: Confirm docs reflect architecture**

Check `README.md`:

- Live mode runs `api.main:app`.
- Scaffold mode runs `notify.approve:app`.
- `REVMEM_BASE_URL` points at the canonical API in live mode.
- Stub mode is explicit via `REVMEM_STUB_MODE=1`.
- Approval tokens are not returned to the agent; human link is printed by the API server.

- [ ] **Step 5: Final status check**

Run: `git status --short`

Expected: only the in-scope files above are modified. Do not revert unrelated pre-existing user changes.

## Test plan

New tests:

- `tests/test_revmem_client.py`
  - explicit stub mode
  - live mode raises on HTTP failures
  - route/status/write wrapper shape
- `tests/test_agent_tools.py`
  - observer tool surface excludes writes
  - analyst/autonomous tool surface includes status polling and writes
- `tests/test_agent_runner.py`
  - retrieve_context returns memories plus policy
  - write_crm calls `revmem_client.write_crm`
  - get_approval_status calls `revmem_client.get_approval_status`

Existing tests to update:

- `tests/test_api.py`
- `tests/test_approval.py`
- `tests/test_governance.py`
- `tests/test_seed.py`
- `evals/test_grade.py`

Verification:

- `uv run pytest` passes.
- `uv run ruff check <edited files>` passes.
- `uv run ty check <edited files>` passes.

## Done criteria

All must hold:

- [ ] Live README instructions start `api.main:app`, not `notify.approve:app`.
- [ ] `agent/revmem_client.py` does not silently fall back to stubs when `REVMEM_BASE_URL` is set unless `REVMEM_STUB_MODE=1`.
- [ ] `data/`, `agent/`, and `evals/` use one field schema for contract and CRM records.
- [ ] API/core and evals agree that `schedule_change` routes to `controller` and `discount_over_authority` routes to `cfo_cco`.
- [ ] `retrieve_context` returns active policy to the live agent.
- [ ] ANALYST/AUTONOMOUS live tools include `get_approval_status` and `write_crm`.
- [ ] `_execute_tool` handles route, status, and write tool calls.
- [ ] The canonical approval/write API test passes with `annual_schedule_usd`.
- [ ] `uv run pytest` passes.
- [ ] `uv run ruff check` passes for all edited files.
- [ ] `uv run ty check` passes for all edited files or only reports clearly documented pre-existing diagnostics outside scope.

## STOP conditions

Stop and report back if:

- The installed `google-genai` Interactions API no longer accepts the existing tool declaration shape from `agent/tools.py`. Query Context7 for `/googleapis/python-genai` before changing SDK syntax.
- Fixing type validation requires a repo-wide typing rewrite outside the in-scope files.
- You need to expose approval tokens to the agent-facing API to make the CLI convenient. That would violate the security boundary; use API server logs for the human link instead.
- The operator wants the older `agent/data/` files kept as canonical. This plan assumes `data/` becomes canonical.
- Any step requires replacing SQLite with Postgres or changing the architecture to the TypeScript plan.

## Maintenance notes

- After this lands, `notify.approve` should be treated as scaffold-only. Do not add new live behavior there.
- Keep the policy returned by `/memory/retrieve` as the live source of policy truth. Static local policy can exist as environment context, but should not override the server.
- Any future policy edit feature must update `data/policy.json`, `core/governance.py` tests, and `evals/gold.py` expectations together.
- If later work adds production auth, keep the server-side `authorize_write` gate. Prompt instructions and tool schemas are not security controls.

## Self-review

- **Spec coverage:** Issues 1-4 are covered by Tasks 1-5. Task 1 fixes wrong live service docs and stub fallback. Task 2 fixes schema/routing drift. Task 3 fixes policy propagation. Task 4 fixes live route/poll/write tool wiring. Task 5 adds cross-boundary regressions.
- **Placeholder scan:** No TBD/TODO placeholders. Every behavioral task has exact files, tests, and verification commands.
- **Type consistency:** Canonical field names are `_usd` names across data, API tests, agent, and evals. `retrieve_context` returns a dict bundle, and all call sites must use `bundle["memories"]` rather than assuming a list.
