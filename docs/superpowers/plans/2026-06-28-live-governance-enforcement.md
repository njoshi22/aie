# Live Governance Enforcement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `uv run python -m cli.run --live` a real governed-agent execution path: fail closed without a real RevMem API, require actual approval tool calls for routed material discrepancies, and prevent bogus one-run autonomy promotion.

**Architecture:** The runner must treat model text as analysis, not governance evidence. Live mode should refuse implicit stub mode unless explicitly requested; the runner should record tool calls and grade material catches only when backed by `route_for_approval` evidence; reputation updates should consume audited outcomes and avoid massive one-session jumps.

**Tech Stack:** Python 3.13, FastAPI, Google GenAI / Antigravity interactions, Rich CLI, SQLite, pytest, Ruff, ty.

## Global Constraints

- Do not log or commit API keys. Any key used for live validation must be passed via environment and rotated afterwards.
- No network-dependent tests. Live Gemini/API checks are manual smoke gates only.
- Do not trust prompt compliance for governance. Enforce workflow invariants in `agent/runner.py` and server-side reputation logic.
- Keep changes focused; do not re-architect the service boundary or replace SQLite/FastAPI in this fix.
- Run `uv run ruff check` and `uv run ty check` on every edited Python file. Full `uv run ty check` is currently allowed to fail on unrelated existing diagnostics; document that if unchanged.
- Before changing Google GenAI interaction syntax, query Context7 for current `google-genai` / FastAPI testing docs.

---

## File Structure

- Modify `cli/run.py`: add explicit live-runtime validation, add `--allow-stub-live`, and display server-returned permission tier after live runs.
- Modify `agent/runner.py`: record structured tool calls, audit material decisions against actual `route_for_approval` calls, and submit only audited outcomes.
- Modify `evals/grade.py`: optionally accept audit notes or keep grade pure and append notes in the runner.
- Modify `core/reputation.py`: smooth reputation updates so one perfect run cannot jump from observer to autonomous.
- Modify `tests/test_agent_runner.py`: add unit tests for route evidence auditing.
- Create `tests/test_cli_run.py`: add tests for live-mode stub rejection.
- Modify `tests/test_reputation.py`: add tests for smoothed promotion.
- Modify `agent/scenarios.py`: correct Session 3 expected material count to match gold data.
- Modify `cli/run.py` scaffold data or README wording: remove the misleading “live” scaffold label and align Session 3 discount behavior with canonical data.
- Modify `README.md`: document that plain `cli.run` is scaffold-only and `--live` requires a real API unless `--allow-stub-live` is used.

---

### Task 1: Fail Closed For Misconfigured Live Mode

**Files:**
- Modify: `cli/run.py`
- Create: `tests/test_cli_run.py`
- Modify: `README.md`

**Interfaces:**
- Produces: `live_runtime_error(stub_mode: bool, base_url: str, allow_stub_live: bool) -> str | None`
- Consumes: `agent.revmem_client.STUB_MODE` and `agent.revmem_client.REVMEM_BASE_URL`

- [ ] **Step 1: Write failing tests for live runtime validation**

Add `tests/test_cli_run.py`:

```python
from __future__ import annotations

from cli.run import live_runtime_error


def test_live_runtime_rejects_implicit_stub_mode() -> None:
    error = live_runtime_error(
        stub_mode=True,
        base_url="",
        allow_stub_live=False,
    )

    assert error is not None
    assert "requires REVMEM_BASE_URL" in error
    assert "--allow-stub-live" in error


def test_live_runtime_allows_real_revmem_api() -> None:
    assert live_runtime_error(
        stub_mode=False,
        base_url="http://127.0.0.1:8000",
        allow_stub_live=False,
    ) is None


def test_live_runtime_allows_explicit_stub_override() -> None:
    assert live_runtime_error(
        stub_mode=True,
        base_url="",
        allow_stub_live=True,
    ) is None
```

- [ ] **Step 2: Run the failing tests**

Run:

```bash
uv run pytest tests/test_cli_run.py -v
```

Expected: fail because `live_runtime_error` does not exist.

- [ ] **Step 3: Implement live runtime validation**

In `cli/run.py`, add near the CLI helpers:

```python
def live_runtime_error(stub_mode: bool, base_url: str, allow_stub_live: bool) -> str | None:
    if stub_mode and not allow_stub_live:
        return (
            "--live requires REVMEM_BASE_URL pointing at the RevMem API. "
            "Start `uv run uvicorn api.main:app --port 8000` and set "
            "`REVMEM_BASE_URL=http://127.0.0.1:8000`, or pass "
            "`--allow-stub-live` for an explicit offline smoke run."
        )
    if not stub_mode and not base_url:
        return "REVMEM_BASE_URL is empty even though stub mode is disabled."
    return None
```

In `main()`, add the argument:

```python
parser.add_argument(
    "--allow-stub-live",
    action="store_true",
    help="allow --live to use offline RevMem stubs; diagnostic only",
)
```

Before any `run_live*` branch executes:

```python
if args.live:
    from agent import revmem_client

    error = live_runtime_error(
        stub_mode=revmem_client.STUB_MODE,
        base_url=revmem_client.REVMEM_BASE_URL,
        allow_stub_live=args.allow_stub_live,
    )
    if error:
        parser.error(error)
```

- [ ] **Step 4: Verify tests pass**

Run:

```bash
uv run pytest tests/test_cli_run.py -v
uv run ruff check cli/run.py tests/test_cli_run.py
uv run ty check cli/run.py tests/test_cli_run.py
```

Expected: all pass.

- [ ] **Step 5: Update README live-mode docs**

In `README.md`, update the live CLI section to say:

```markdown
`uv run python -m cli.run` is scaffold-only and does not call Gemini.
`uv run python -m cli.run --live` calls Gemini and refuses to run unless
`REVMEM_BASE_URL` points at a running RevMem API. Use `--allow-stub-live`
only for explicit offline diagnostics.
```

- [ ] **Step 6: Commit**

```bash
git add cli/run.py tests/test_cli_run.py README.md
git commit -m "Fail closed for misconfigured live CLI"
```

---

### Task 2: Record Tool Calls As First-Class Evidence

**Files:**
- Modify: `agent/runner.py`
- Modify: `tests/test_agent_runner.py`

**Interfaces:**
- Produces: `ToolCallRecord`
- Produces: `tool_calls: list[ToolCallRecord]` in `run_session()` result
- Consumes: `_execute_tool(name, arguments, agent_id, session_id)`

- [ ] **Step 1: Add failing test for structured tool recording helper**

In `tests/test_agent_runner.py`, add:

```python
from agent.runner import ToolCallRecord


def test_tool_call_record_shape() -> None:
    record: ToolCallRecord = {
        "name": "route_for_approval",
        "arguments": {"deal_id": "globex", "change_type": "schedule_change"},
        "result": {"approval_id": "appr-1", "route_to": "controller"},
    }

    assert record["name"] == "route_for_approval"
    assert record["arguments"]["deal_id"] == "globex"
    assert record["result"]["route_to"] == "controller"
```

- [ ] **Step 2: Run the failing test**

```bash
uv run pytest tests/test_agent_runner.py::test_tool_call_record_shape -v
```

Expected: fail because `ToolCallRecord` is not exported.

- [ ] **Step 3: Add `ToolCallRecord` and record full calls**

In `agent/runner.py`, add near `JsonObject`:

```python
class ToolCallRecord(TypedDict):
    name: str
    arguments: JsonObject
    result: JsonObject
```

Change:

```python
tool_calls_made = []
```

to:

```python
tool_calls_made: list[ToolCallRecord] = []
```

Change the append inside the tool loop from:

```python
tool_calls_made.append(tool_name)
```

to:

```python
# after tool_result is computed
tool_calls_made.append({
    "name": tool_name,
    "arguments": tool_args,
    "result": tool_result,
})
```

Add to the final `result` dict:

```python
"tool_calls": tool_calls_made,
```

- [ ] **Step 4: Verify scoped tests and types**

```bash
uv run pytest tests/test_agent_runner.py -v
uv run ruff check agent/runner.py tests/test_agent_runner.py
uv run ty check agent/runner.py tests/test_agent_runner.py
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add agent/runner.py tests/test_agent_runner.py
git commit -m "Record live runner tool evidence"
```

---

### Task 3: Require Approval Tool Evidence For Material Credit

**Files:**
- Modify: `agent/runner.py`
- Modify: `tests/test_agent_runner.py`

**Interfaces:**
- Consumes: `evals.grade.Decision`
- Consumes: `evals.gold.GoldItem`
- Consumes: `ToolCallRecord`
- Produces: `audit_decisions_for_tool_evidence(deal: str, decisions: list[Decision], gold: list[GoldItem], tool_calls: list[ToolCallRecord]) -> tuple[list[Decision], list[str]]`

- [ ] **Step 1: Add failing tests for missing and present approval evidence**

In `tests/test_agent_runner.py`, add:

```python
from evals.gold import GoldItem
from evals.grade import Decision
from agent.runner import audit_decisions_for_tool_evidence


def _gold_schedule() -> GoldItem:
    return GoldItem(
        field="annual_schedule_usd",
        contract=[80000, 120000, 160000],
        crm=[120000, 120000, 120000],
        diff_usd=40000.0,
        change_type="schedule_change",
        material=True,
        expected_action="escalate",
        expected_route="controller",
    )


def test_material_decision_without_route_tool_is_downgraded() -> None:
    audited, notes = audit_decisions_for_tool_evidence(
        deal="globex",
        decisions=[Decision("annual_schedule_usd", "escalate", route_to="controller")],
        gold=[_gold_schedule()],
        tool_calls=[],
    )

    assert audited == [Decision("annual_schedule_usd", "miss")]
    assert notes == ["annual_schedule_usd: missing route_for_approval tool call"]


def test_material_decision_with_route_tool_uses_tool_route() -> None:
    audited, notes = audit_decisions_for_tool_evidence(
        deal="globex",
        decisions=[Decision("annual_schedule_usd", "escalate", route_to="controller")],
        gold=[_gold_schedule()],
        tool_calls=[
            {
                "name": "route_for_approval",
                "arguments": {
                    "deal_id": "globex",
                    "amount_usd": 40000.0,
                    "change_type": "schedule_change",
                    "summary": "schedule mismatch",
                },
                "result": {
                    "approval_id": "appr-1",
                    "route_to": "controller",
                    "status": "pending",
                },
            }
        ],
    )

    assert audited == [Decision("annual_schedule_usd", "escalate", route_to="controller")]
    assert notes == []
```

- [ ] **Step 2: Run failing tests**

```bash
uv run pytest \
  tests/test_agent_runner.py::test_material_decision_without_route_tool_is_downgraded \
  tests/test_agent_runner.py::test_material_decision_with_route_tool_uses_tool_route \
  -v
```

Expected: fail because `audit_decisions_for_tool_evidence` does not exist.

- [ ] **Step 3: Implement route evidence audit**

In `agent/runner.py`, add:

```python
from evals.gold import GoldItem
from evals.grade import Decision
```

Add the helper:

```python
def _route_evidence_by_change_type(tool_calls: list[ToolCallRecord]) -> dict[tuple[str, str], JsonObject]:
    evidence: dict[tuple[str, str], JsonObject] = {}
    for call in tool_calls:
        if call["name"] != "route_for_approval":
            continue
        deal_id = str(call["arguments"].get("deal_id", ""))
        change_type = str(call["arguments"].get("change_type", ""))
        if deal_id and change_type:
            evidence[(deal_id, change_type)] = call["result"]
    return evidence


def audit_decisions_for_tool_evidence(
    deal: str,
    decisions: list[Decision],
    gold: list[GoldItem],
    tool_calls: list[ToolCallRecord],
) -> tuple[list[Decision], list[str]]:
    evidence = _route_evidence_by_change_type(tool_calls)
    gold_by_field = {item.field: item for item in gold}
    audited: list[Decision] = []
    notes: list[str] = []

    for decision in decisions:
        item = gold_by_field.get(decision.field)
        if item is None or not item.material:
            audited.append(decision)
            continue

        change_type = item.change_type or ""
        route = evidence.get((deal, change_type))
        if route is None:
            audited.append(Decision(decision.field, "miss"))
            notes.append(f"{decision.field}: missing route_for_approval tool call")
            continue

        audited.append(
            Decision(
                decision.field,
                decision.action,
                route_to=str(route.get("route_to", decision.route_to or "")) or None,
            )
        )

    return audited, notes
```

- [ ] **Step 4: Verify tests pass**

```bash
uv run pytest tests/test_agent_runner.py -v
uv run ruff check agent/runner.py tests/test_agent_runner.py
uv run ty check agent/runner.py tests/test_agent_runner.py
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add agent/runner.py tests/test_agent_runner.py
git commit -m "Require route tool evidence for material credit"
```

---

### Task 4: Submit Only Audited Outcomes

**Files:**
- Modify: `agent/runner.py`
- Modify: `tests/test_agent_runner.py`

**Interfaces:**
- Consumes: `audit_decisions_for_tool_evidence(...)`
- Produces: `result["audit_notes"]`
- Produces: `complete_session(session_id, audited_outcome)`

- [ ] **Step 1: Add a focused test for audited grading behavior**

In `tests/test_agent_runner.py`, add:

```python
from evals.grade import grade


def test_missing_route_tool_makes_scorecard_fail_material_recall() -> None:
    audited, notes = audit_decisions_for_tool_evidence(
        deal="globex",
        decisions=[Decision("annual_schedule_usd", "escalate", route_to="controller")],
        gold=[_gold_schedule()],
        tool_calls=[],
    )
    scorecard = grade("globex", audited, [_gold_schedule()])
    scorecard.notes.extend(notes)

    assert scorecard.outcome["accuracy"] == 0.0
    assert scorecard.outcome["material_caught"] == 0
    assert "missing route_for_approval" in scorecard.notes[-1]
```

- [ ] **Step 2: Run the failing test**

```bash
uv run pytest tests/test_agent_runner.py::test_missing_route_tool_makes_scorecard_fail_material_recall -v
```

Expected: fail until Task 3 helper exists and is wired correctly.

- [ ] **Step 3: Wire audited decisions into `run_session()`**

In `agent/runner.py`, replace:

```python
scorecard = grade(deal, decisions, build_gold(deal))
outcome = scorecard.outcome
```

with:

```python
gold = build_gold(deal)
audited_decisions, audit_notes = audit_decisions_for_tool_evidence(
    deal,
    decisions,
    gold,
    tool_calls_made,
)
scorecard = grade(deal, audited_decisions, gold)
scorecard.notes.extend(audit_notes)
outcome = scorecard.outcome
```

Add to the returned `result`:

```python
"audit_notes": audit_notes,
```

- [ ] **Step 4: Verify the previous live failure mode now fails offline under unit tests**

```bash
uv run pytest tests/test_agent_runner.py -v
uv run ruff check agent/runner.py tests/test_agent_runner.py
uv run ty check agent/runner.py tests/test_agent_runner.py
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add agent/runner.py tests/test_agent_runner.py
git commit -m "Grade live sessions from audited tool evidence"
```

---

### Task 5: Smooth Reputation Promotion

**Files:**
- Modify: `core/reputation.py`
- Modify: `tests/test_reputation.py`
- Modify: `cli/run.py`

**Interfaces:**
- Produces: `MAX_REPUTATION_STEP = 0.25`
- Updates: `update_after_session(conn: sqlite3.Connection, agent_id: str) -> Agent`
- Updates: `RichListener.on_session_end(...)` to display `permission_tier` from server response when available.

- [ ] **Step 1: Add failing reputation smoothing test**

In `tests/test_reputation.py`, add:

```python
def test_one_perfect_session_does_not_jump_to_autonomous(conn) -> None:
    a = Agent(name="bounded")
    database.insert_agent(conn, a)

    _run(conn, a.id, 1.0)

    got = database.get_agent(conn, a.id)
    assert got is not None
    assert got.reputation_score == 0.35
    assert got.permission_tier == PermissionTier.ANALYST
```

- [ ] **Step 2: Run failing test**

```bash
uv run pytest tests/test_reputation.py::test_one_perfect_session_does_not_jump_to_autonomous -v
```

Expected: fail because current score jumps to `1.0`.

- [ ] **Step 3: Implement bounded score movement**

In `core/reputation.py`, add:

```python
MAX_REPUTATION_STEP = 0.25


def _bounded_score(previous: float, target: float) -> float:
    delta = max(-MAX_REPUTATION_STEP, min(MAX_REPUTATION_STEP, target - previous))
    return max(0.0, min(1.0, round(previous + delta, 3)))
```

Change `update_after_session()` from:

```python
agent.reputation_score = compute(success_rate, avg_accuracy)
```

to:

```python
target_score = compute(success_rate, avg_accuracy)
agent.reputation_score = _bounded_score(agent.reputation_score, target_score)
```

- [ ] **Step 4: Display server permission tier in live CLI**

In `cli/run.py`, change `RichListener.on_session_end()` after `updated = revmem_client.get_agent(...)`:

```python
rep = float(updated.get("reputation_score", rep))
tier = str(updated.get("permission_tier", tier_for(rep)))
```

This prevents the CLI from deriving a tier that disagrees with server policy.

- [ ] **Step 5: Verify reputation tests and CLI types**

```bash
uv run pytest tests/test_reputation.py -v
uv run ruff check core/reputation.py cli/run.py tests/test_reputation.py
uv run ty check core/reputation.py cli/run.py tests/test_reputation.py
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add core/reputation.py cli/run.py tests/test_reputation.py
git commit -m "Bound reputation promotion per session"
```

---

### Task 6: Align Session 3 Scenario And Scaffold With Gold Data

**Files:**
- Modify: `agent/scenarios.py`
- Modify: `cli/run.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: canonical `data/contracts.json` and `data/salesforce.json`
- Produces: consistent Session 3 claim: annual schedule mismatch plus over-authority discount.

- [ ] **Step 1: Add failing scenario consistency test**

Create or extend `tests/test_scenarios.py`:

```python
from __future__ import annotations

from agent.scenarios import SCENARIOS
from evals.gold import build_gold


def test_session_three_expected_material_count_matches_gold() -> None:
    material_total = sum(1 for item in build_gold("globex") if item.material)

    assert SCENARIOS[3]["expected"]["material_caught"] == material_total
```

- [ ] **Step 2: Run failing test**

```bash
uv run pytest tests/test_scenarios.py -v
```

Expected: fail because Session 3 currently says `material_caught: 1` while gold has 2 material issues.

- [ ] **Step 3: Fix `agent/scenarios.py`**

Change Session 3 expected block:

```python
"expected": {
    "material_caught": 2,
    "false_escalations": 0,
    "accuracy": 1.0,
    "description": (
        "Lesson generalizes to new deal. Agent catches the ramp schedule mismatch "
        "and escalates the 25% discount over deal-desk authority to CFO/CCO."
    ),
},
```

- [ ] **Step 4: Fix scaffold labeling and data**

In `cli/run.py`, change scaffold Session 3 name from:

```python
"session_name": "Session 3 - live (ANALYST)",
```

to:

```python
"session_name": "Session 3 - scaffold (ANALYST)",
```

Change the scaffold discount row:

```python
{"field": "Discount", "contract": "25%", "crm": "20%", "verdict": "material"},
```

If the scaffold still routes only one approval, add a comment-free visible route for the discount row by appending the discount discrepancy to the routing panel text:

```python
"discrepancy": (
    "Year-1 revenue understated: CRM flat $120k vs ramped $80k schedule. "
    "Discount also exceeds deal-desk authority: signed 25% vs CRM 20%."
),
```

- [ ] **Step 5: Verify scaffold smoke**

```bash
uv run python -m cli.run --fast --no-wait
uv run pytest tests/test_scenarios.py -v
uv run ruff check agent/scenarios.py cli/run.py tests/test_scenarios.py
uv run ty check agent/scenarios.py cli/run.py tests/test_scenarios.py
```

Expected: command exits 0 and the heading says scaffold, not live.

- [ ] **Step 6: Commit**

```bash
git add agent/scenarios.py cli/run.py README.md tests/test_scenarios.py
git commit -m "Align session three scenario with gold data"
```

---

### Task 7: End-To-End Validation

**Files:**
- No new code unless earlier gates fail.

**Interfaces:**
- Verifies the complete behavior across CLI, runner, API client, reputation, and tests.

- [ ] **Step 1: Run targeted regression suite**

```bash
uv run pytest \
  tests/test_cli_run.py \
  tests/test_agent_runner.py \
  tests/test_reputation.py \
  tests/test_scenarios.py \
  tests/test_revmem_client.py \
  tests/test_approval.py \
  -v
```

Expected: all pass.

- [ ] **Step 2: Run full test suite**

```bash
uv run pytest
```

Expected: all pass.

- [ ] **Step 3: Run full lint**

```bash
uv run ruff check
```

Expected: all pass.

- [ ] **Step 4: Run scoped type validation for edited files**

```bash
uv run ty check \
  cli/run.py \
  agent/runner.py \
  evals/grade.py \
  core/reputation.py \
  tests/test_cli_run.py \
  tests/test_agent_runner.py \
  tests/test_reputation.py \
  tests/test_scenarios.py
```

Expected: all pass.

- [ ] **Step 5: Record current full type-check status**

```bash
uv run ty check
```

Expected: may still fail on pre-existing unrelated diagnostics in `agent/spike.py`, `evals/harness.py`, and nullable test assertions unless separately fixed. Do not claim full project type clean unless this command passes.

- [ ] **Step 6: Manual live smoke without real API must fail closed**

```bash
GEMINI_API_KEY=redacted uv run python -m cli.run --live
```

Expected: exits before any Gemini call with a message requiring `REVMEM_BASE_URL` or `--allow-stub-live`.

- [ ] **Step 7: Manual live smoke with local API must not grant fake credit**

Terminal 1:

```bash
uv run uvicorn api.main:app --host 127.0.0.1 --port 8010
```

Terminal 2:

```bash
GEMINI_API_KEY=redacted \
REVMEM_BASE_URL=http://127.0.0.1:8010 \
REVMEM_STUB_MODE=0 \
uv run python -m cli.run --live --no-wait
```

Expected if the model still skips `route_for_approval`: outcome is not perfect, audit notes mention missing approval tool calls, and reputation does not jump to autonomous.

Expected if the model calls `route_for_approval`: API logs include `/route_for_approval`, the CLI shows approval routing, and credit is based on the tool result.

- [ ] **Step 8: Final commit or squash**

If tasks were committed separately, keep them separate unless the reviewer wants a squash. Do not force-push without explicit instruction.

---

## Self-Review

**Spec coverage:** The plan covers live stub-mode misconfiguration, missing approval tool calls, self-graded outcomes, reputation over-promotion, and Session 3 gold/scenario mismatch.

**Placeholder scan:** No `TBD`, vague “add validation”, or test-free implementation steps remain.

**Type consistency:** `ToolCallRecord`, `JsonObject`, `Decision`, and `GoldItem` names match the current codebase. The plan keeps Google GenAI interaction syntax unchanged except for local result bookkeeping.
