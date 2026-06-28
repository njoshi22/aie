# Pre-Tool-Use Approval Hook Implementation Plan

> Superseded by `docs/superpowers/plans/2026-06-28-service-layer-approval-contract.md`. The repo is a service layer, so approvals are now route/method policy with OR/AND approver graphs and dependencies, not runner-owned pre-tool hooks.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move approval enforcement for privileged agent actions into a typed pre-tool-use hook, so approval routing happens before `write_crm` executes instead of as post-run runner repair.

**Architecture:** Add a small `agent/tool_policy.py` hook layer that runs before every model-requested tool execution. The hook enforces tier permissions, routes required approvals before privileged writes, blocks writes until approval exists, and emits structured hook evidence; `agent/runner.py` remains the Antigravity transport loop and scorer. The existing end-of-run audit remains necessary because a pre-tool-use hook cannot fire when the model never attempts a governed tool.

**Tech Stack:** Python 3.11+, FastAPI, Google GenAI / Antigravity interactions, Rich CLI, SQLite, pytest, Ruff, ty.

## Global Constraints

- Do not add post-model approval repair in `run_session()`. Approval side effects belong in the pre-tool-use hook or the server API.
- Keep server-side enforcement in `api/routes.py` unchanged as the final authority for `write_crm`.
- The hook only intercepts attempted tool calls. If the model skips both `route_for_approval` and `write_crm`, the session must remain a compliance/scoring failure.
- Do not log or commit API keys. Any live Gemini key used for manual validation must be passed via environment and rotated after exposure.
- No network-dependent automated tests. Gemini/live API checks are manual smoke gates only.
- Use Context7 before changing Google GenAI or Antigravity interaction syntax. This plan does not require SDK syntax changes.
- Run `uv run ruff check` and scoped `uv run ty check` for every edited Python file. Full `uv run ty check` currently has unrelated existing failures; document the result instead of claiming full type-clean if it still fails.
- Do not delete branches automatically when pushing.

---

## File Structure

- Create `agent/tool_types.py`: shared JSON and tool-call evidence types used by runner and hook code.
- Create `agent/tool_policy.py`: pre-tool-use hook, approval client protocol, and write-gate policy.
- Modify `agent/runner.py`: call the hook before `_execute_tool`, record hook-generated approval evidence, and pass blocked write results back to the model as function results.
- Modify `tests/test_tool_policy.py`: unit tests for the hook without Gemini or HTTP.
- Modify `tests/test_agent_runner.py`: integration-style runner tests for hook-routed approvals and audit behavior.
- Modify `cli/run.py`: render hook-routed approvals clearly in live output.
- Modify `README.md`: document that approval enforcement happens at the pre-tool-use boundary and that final-answer-only routing is still non-compliant.
- Do not modify `AGENTS.md`; this repo currently has no top-level `AGENTS.md` file to update.

---

### Task 1: Add Shared Tool Evidence Types

**Files:**
- Create: `agent/tool_types.py`
- Modify: `agent/runner.py`
- Modify: `tests/test_agent_runner.py`

**Interfaces:**
- Produces: `JsonObject`
- Produces: `ToolCallSource = Literal["model", "pre_tool_hook"]`
- Produces: `ToolCallRecord` with optional `source`
- Consumes: existing `ToolCallRecord` tests and runner result shape

- [ ] **Step 1: Write the failing test for source-aware tool evidence**

In `tests/test_agent_runner.py`, update the import and test so `ToolCallRecord` comes from the shared module and accepts a hook source:

```python
from agent.tool_types import ToolCallRecord


def test_tool_call_record_shape() -> None:
    record: ToolCallRecord = {
        "name": "route_for_approval",
        "arguments": {"deal_id": "globex", "change_type": "schedule_change"},
        "result": {"approval_id": "appr-1", "route_to": "controller"},
        "source": "pre_tool_hook",
    }

    assert record["name"] == "route_for_approval"
    assert record["arguments"]["deal_id"] == "globex"
    assert record["result"]["route_to"] == "controller"
    assert record["source"] == "pre_tool_hook"
```

- [ ] **Step 2: Run the failing test**

Run:

```bash
uv run pytest tests/test_agent_runner.py::test_tool_call_record_shape -v
```

Expected: fail because `agent.tool_types` does not exist.

- [ ] **Step 3: Create the shared types**

Create `agent/tool_types.py`:

```python
from __future__ import annotations

from typing import Literal, NotRequired, TypeAlias, TypedDict

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]
ToolCallSource: TypeAlias = Literal["model", "pre_tool_hook"]


class ToolCallRecord(TypedDict):
    name: str
    arguments: JsonObject
    result: JsonObject
    source: NotRequired[ToolCallSource]
```

- [ ] **Step 4: Point the runner at the shared types**

In `agent/runner.py`, replace the local aliases and local `ToolCallRecord` definition with:

```python
from agent.tool_types import JsonObject, ToolCallRecord
```

Remove this local code from `agent/runner.py`:

```python
JsonObject = dict[str, Any]


class ToolCallRecord(TypedDict):
    name: str
    arguments: JsonObject
    result: JsonObject
```

Keep `Any`, `Protocol`, `TypedDict`, and `cast` imports only if still used by other code in the file.

- [ ] **Step 5: Mark model-originated tool calls**

In `agent/runner.py`, change the append inside the existing tool loop from:

```python
tool_calls_made.append({
    "name": tool_name,
    "arguments": tool_args,
    "result": tool_result,
})
```

to:

```python
tool_calls_made.append({
    "name": tool_name,
    "arguments": tool_args,
    "result": tool_result,
    "source": "model",
})
```

- [ ] **Step 6: Verify Task 1**

Run:

```bash
uv run pytest tests/test_agent_runner.py::test_tool_call_record_shape -v
uv run ruff check agent/tool_types.py agent/runner.py tests/test_agent_runner.py
uv run ty check agent/tool_types.py agent/runner.py tests/test_agent_runner.py
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add agent/tool_types.py agent/runner.py tests/test_agent_runner.py
git commit -m "Share structured tool evidence types"
```

---

### Task 2: Implement The Pre-Tool-Use Approval Hook

**Files:**
- Create: `agent/tool_policy.py`
- Create: `tests/test_tool_policy.py`

**Interfaces:**
- Produces: `ToolUseRequest`
- Produces: `PreToolUseDecision`
- Produces: `ApprovalClient` protocol
- Produces: `before_tool_use(request: ToolUseRequest, approvals: ApprovalClient) -> PreToolUseDecision`
- Consumes: `core.governance.can_use(...)`
- Consumes: `core.governance.authorize_write(...)`

- [ ] **Step 1: Write failing hook tests**

Create `tests/test_tool_policy.py`:

```python
from __future__ import annotations

from agent.tool_policy import ToolUseRequest, before_tool_use
from agent.tool_types import JsonObject
from core.models import ApprovalStatus, PermissionTier


class FakeApprovals:
    def __init__(self, status: str = ApprovalStatus.PENDING) -> None:
        self.status = status
        self.route_calls: list[tuple[str, float, str, JsonObject]] = []
        self.status_calls: list[str] = []

    def route_for_approval(
        self,
        deal_id: str,
        amount_usd: float,
        change_type: str,
        **extra: object,
    ) -> JsonObject:
        payload: JsonObject = {
            "approval_id": "appr-1",
            "route_to": "controller",
            "status": "pending",
        }
        self.route_calls.append((deal_id, amount_usd, change_type, {"summary": str(extra.get("summary", ""))}))
        return payload

    def get_approval_status(self, approval_id: str) -> JsonObject:
        self.status_calls.append(approval_id)
        return {"id": approval_id, "status": self.status}


def _write_request(
    tier: str,
    approval_id: str | None = None,
    change_type: str = "schedule_change",
) -> ToolUseRequest:
    args: JsonObject = {
        "deal_id": "globex",
        "fields": {"annual_schedule_usd": [80000, 120000, 160000]},
        "discrepancy": {
            "deal_id": "globex",
            "amount_usd": 40000.0,
            "change_type": change_type,
        },
    }
    if approval_id is not None:
        args["approval_id"] = approval_id
    return ToolUseRequest(
        name="write_crm",
        arguments=args,
        agent_id="agent-1",
        session_id="session-1",
        tier=tier,
    )


def test_hook_allows_observer_read_tool() -> None:
    decision = before_tool_use(
        ToolUseRequest(
            name="retrieve_context",
            arguments={"query": "globex ramp"},
            agent_id="agent-1",
            session_id="session-1",
            tier=PermissionTier.OBSERVER,
        ),
        FakeApprovals(),
    )

    assert decision.allow is True
    assert decision.result is None
    assert decision.tool_records == ()


def test_hook_denies_tool_not_allowed_for_tier() -> None:
    approvals = FakeApprovals()

    decision = before_tool_use(_write_request(PermissionTier.OBSERVER), approvals)

    assert decision.allow is False
    assert decision.result == {
        "error": "tier observer cannot use write_crm",
        "policy_decision": "deny",
        "skipped": True,
    }
    assert approvals.route_calls == []


def test_hook_routes_analyst_write_before_execution() -> None:
    approvals = FakeApprovals()

    decision = before_tool_use(_write_request(PermissionTier.ANALYST), approvals)

    assert decision.allow is False
    assert decision.result is not None
    assert decision.result["approval_required"] is True
    assert decision.result["approval_id"] == "appr-1"
    assert approvals.route_calls == [
        (
            "globex",
            40000.0,
            "schedule_change",
            {"summary": "write_crm requested for globex schedule_change 40000.00"},
        )
    ]
    assert decision.tool_records == (
        {
            "name": "route_for_approval",
            "arguments": {
                "deal_id": "globex",
                "amount_usd": 40000.0,
                "change_type": "schedule_change",
                "summary": "write_crm requested for globex schedule_change 40000.00",
            },
            "result": {
                "approval_id": "appr-1",
                "route_to": "controller",
                "status": "pending",
            },
            "source": "pre_tool_hook",
        },
    )


def test_hook_allows_write_with_approved_approval_id() -> None:
    approvals = FakeApprovals(status=ApprovalStatus.APPROVED)

    decision = before_tool_use(_write_request(PermissionTier.ANALYST, approval_id="appr-1"), approvals)

    assert decision.allow is True
    assert decision.result is None
    assert approvals.status_calls == ["appr-1"]


def test_hook_blocks_write_with_pending_approval_id() -> None:
    approvals = FakeApprovals(status=ApprovalStatus.PENDING)

    decision = before_tool_use(_write_request(PermissionTier.ANALYST, approval_id="appr-1"), approvals)

    assert decision.allow is False
    assert decision.result == {
        "error": "write_crm blocked until approval appr-1 is approved",
        "approval_required": True,
        "approval_id": "appr-1",
        "approval_status": "pending",
        "policy_decision": "needs_approval",
        "skipped": True,
    }
```

- [ ] **Step 2: Run the failing tests**

Run:

```bash
uv run pytest tests/test_tool_policy.py -v
```

Expected: fail because `agent.tool_policy` does not exist.

- [ ] **Step 3: Implement the hook**

Create `agent/tool_policy.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from agent.tool_types import JsonObject, JsonValue, ToolCallRecord
from core import governance


class ApprovalClient(Protocol):
    def route_for_approval(
        self,
        deal_id: str,
        amount_usd: float,
        change_type: str,
        **extra: object,
    ) -> JsonObject: ...

    def get_approval_status(self, approval_id: str) -> JsonObject: ...


@dataclass(frozen=True)
class ToolUseRequest:
    name: str
    arguments: JsonObject
    agent_id: str
    session_id: str
    tier: str


@dataclass(frozen=True)
class PreToolUseDecision:
    allow: bool
    result: JsonObject | None = None
    tool_records: tuple[ToolCallRecord, ...] = ()


def _object_arg(arguments: JsonObject, key: str) -> JsonObject:
    value = arguments.get(key)
    return value if isinstance(value, dict) else {}


def _string_arg(arguments: JsonObject, key: str) -> str:
    value = arguments.get(key)
    return value if isinstance(value, str) else ""


def _string_value(value: JsonValue, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _float_value(value: JsonValue, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    return default


def _route_summary(deal_id: str, amount_usd: float, change_type: str) -> str:
    return f"write_crm requested for {deal_id} {change_type} {amount_usd:.2f}"


def _deny(message: str) -> PreToolUseDecision:
    return PreToolUseDecision(
        allow=False,
        result={
            "error": message,
            "policy_decision": "deny",
            "skipped": True,
        },
    )


def _block_for_approval(approval_id: str, status: str) -> PreToolUseDecision:
    return PreToolUseDecision(
        allow=False,
        result={
            "error": f"write_crm blocked until approval {approval_id} is approved",
            "approval_required": True,
            "approval_id": approval_id,
            "approval_status": status,
            "policy_decision": "needs_approval",
            "skipped": True,
        },
    )


def _route_and_block(request: ToolUseRequest, approvals: ApprovalClient) -> PreToolUseDecision:
    discrepancy = _object_arg(request.arguments, "discrepancy")
    deal_id = _string_arg(request.arguments, "deal_id") or _string_value(discrepancy.get("deal_id", ""))
    amount_usd = _float_value(discrepancy.get("amount_usd", 0.0))
    change_type = _string_value(discrepancy.get("change_type", ""), "unknown")
    summary = _route_summary(deal_id, amount_usd, change_type)
    route_args: JsonObject = {
        "deal_id": deal_id,
        "amount_usd": amount_usd,
        "change_type": change_type,
        "summary": summary,
    }
    approval = approvals.route_for_approval(
        deal_id,
        amount_usd,
        change_type,
        summary=summary,
    )
    approval_id = str(approval.get("approval_id", ""))
    status = str(approval.get("status", "pending"))
    route_record: ToolCallRecord = {
        "name": "route_for_approval",
        "arguments": route_args,
        "result": approval,
        "source": "pre_tool_hook",
    }
    return PreToolUseDecision(
        allow=False,
        result={
            "error": f"write_crm blocked until approval {approval_id} is approved",
            "approval_required": True,
            "approval_id": approval_id,
            "approval_status": status,
            "route_to": str(approval.get("route_to", "")),
            "policy_decision": "needs_approval",
            "skipped": True,
        },
        tool_records=(route_record,),
    )


def before_tool_use(request: ToolUseRequest, approvals: ApprovalClient) -> PreToolUseDecision:
    if not governance.can_use(request.tier, request.name):
        return _deny(f"tier {request.tier} cannot use {request.name}")

    if request.name != "write_crm":
        return PreToolUseDecision(allow=True)

    discrepancy = _object_arg(request.arguments, "discrepancy")
    approval_id = _string_arg(request.arguments, "approval_id")
    if approval_id:
        approval_status = approvals.get_approval_status(approval_id)
        status = str(approval_status.get("status", "pending"))
        decision = governance.authorize_write(request.tier, discrepancy, status)
        if decision == governance.WriteDecision.ALLOW:
            return PreToolUseDecision(allow=True)
        return _block_for_approval(approval_id, status)

    decision = governance.authorize_write(request.tier, discrepancy)
    if decision == governance.WriteDecision.ALLOW:
        return PreToolUseDecision(allow=True)
    if decision == governance.WriteDecision.DENY:
        return _deny(f"write_crm not allowed for tier {request.tier}")
    return _route_and_block(request, approvals)
```

- [ ] **Step 4: Verify Task 2**

Run:

```bash
uv run pytest tests/test_tool_policy.py -v
uv run ruff check agent/tool_policy.py agent/tool_types.py tests/test_tool_policy.py
uv run ty check agent/tool_policy.py agent/tool_types.py tests/test_tool_policy.py
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add agent/tool_policy.py agent/tool_types.py tests/test_tool_policy.py
git commit -m "Add pre-tool-use approval hook"
```

---

### Task 3: Wire The Hook Into The Runner

**Files:**
- Modify: `agent/runner.py`
- Modify: `tests/test_agent_runner.py`

**Interfaces:**
- Consumes: `before_tool_use(...)`
- Consumes: `ToolUseRequest`
- Produces: hook-generated `route_for_approval` records in `result["tool_calls"]`
- Produces: blocked `write_crm` function results back to Antigravity

- [ ] **Step 1: Add a runner regression for hook-routed writes**

In `tests/test_agent_runner.py`, add:

```python
def test_run_session_routes_approval_in_pre_tool_hook(monkeypatch) -> None:
    from agent.runner import run_session
    from core.models import PermissionTier

    class FakeStep:
        def __init__(self, data: dict[str, object]) -> None:
            self._data = data

        def to_dict(self) -> dict[str, object]:
            return self._data

    class FakeInteraction:
        def __init__(
            self,
            status: str,
            steps: list[FakeStep] | None = None,
            output_text: str | None = None,
        ) -> None:
            self.status = status
            self.steps = steps or []
            self.output_text = output_text
            self.id = f"interaction-{status}"
            self.environment_id = "env-1"

    class FakeInteractions:
        def __init__(self) -> None:
            self.calls = 0
            self.function_results: list[list[dict[str, object]]] = []

        def create(self, **kwargs: object) -> FakeInteraction:
            self.calls += 1
            payload = kwargs.get("input")
            if isinstance(payload, list):
                self.function_results.append(payload)
            if self.calls == 1:
                return FakeInteraction(
                    "requires_action",
                    steps=[
                        FakeStep(
                            {
                                "type": "function_call",
                                "id": "call-1",
                                "name": "write_crm",
                                "arguments": {
                                    "deal_id": "globex",
                                    "fields": {"annual_schedule_usd": [80000, 120000, 160000]},
                                    "discrepancy": {
                                        "deal_id": "globex",
                                        "amount_usd": 40000.0,
                                        "change_type": "schedule_change",
                                    },
                                },
                            }
                        )
                    ],
                )
            return FakeInteraction(
                "completed",
                output_text=json.dumps(
                    {
                        "deal_id": "globex",
                        "fields_compared": [
                            {
                                "field": "annual_schedule_usd",
                                "match": False,
                                "materiality": "material",
                                "recommended_action": "escalate",
                                "route_to": "controller",
                            }
                        ],
                    }
                ),
            )

    class FakeClient:
        def __init__(self) -> None:
            self.interactions = FakeInteractions()

    fake_client = FakeClient()
    route_calls: list[tuple[str, float, str]] = []
    write_calls: list[str] = []

    def fake_route_for_approval(
        deal_id: str,
        amount_usd: float,
        change_type: str,
        **extra: object,
    ) -> dict[str, object]:
        route_calls.append((deal_id, amount_usd, change_type))
        return {"approval_id": "appr-1", "route_to": "controller", "status": "pending"}

    def fake_write_crm(**kwargs: object) -> dict[str, object]:
        write_calls.append(str(kwargs.get("deal_id", "")))
        return {"ok": True}

    completed: list[dict[str, object]] = []

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr("agent.runner.genai.Client", lambda api_key: fake_client)
    monkeypatch.setattr(
        "agent.runner.revmem_client.ensure_agent",
        lambda name: {
            "id": "agent-1",
            "permission_tier": PermissionTier.ANALYST,
            "reputation_score": 0.35,
        },
    )
    monkeypatch.setattr("agent.runner.revmem_client.start_session", lambda agent_id, task: {"id": "session-1"})
    monkeypatch.setattr("agent.runner.revmem_client.route_for_approval", fake_route_for_approval)
    monkeypatch.setattr("agent.runner.revmem_client.write_crm", fake_write_crm)
    monkeypatch.setattr("agent.runner.revmem_client.complete_session", lambda session_id, outcome: completed.append(outcome) or {})

    result = run_session(3)

    assert route_calls == [("globex", 40000.0, "schedule_change")]
    assert write_calls == []
    assert result["tool_calls"][0]["name"] == "route_for_approval"
    assert result["tool_calls"][0]["source"] == "pre_tool_hook"
    assert result["tool_calls"][1]["name"] == "write_crm"
    assert result["tool_calls"][1]["result"]["approval_required"] is True
    assert fake_client.interactions.function_results[0][0]["result"]["approval_required"] is True
```

- [ ] **Step 2: Run the failing runner regression**

Run:

```bash
uv run pytest tests/test_agent_runner.py::test_run_session_routes_approval_in_pre_tool_hook -v
```

Expected: fail because `run_session()` does not call the hook.

- [ ] **Step 3: Import the hook in the runner**

In `agent/runner.py`, add:

```python
from agent.tool_policy import ToolUseRequest, before_tool_use
```

- [ ] **Step 4: Add an approval display helper**

In `agent/runner.py`, add near `_route_evidence_by_change_type(...)`:

```python
def _approval_payload(arguments: JsonObject, result: JsonObject, source: str) -> JsonObject:
    payload: JsonObject = dict(result)
    for key in ("deal_id", "amount_usd", "change_type", "summary"):
        if key in arguments:
            payload[key] = arguments[key]
    payload["source"] = source
    return payload
```

- [ ] **Step 5: Execute hook records before the original tool call result**

In `agent/runner.py`, inside the `for fc in fc_steps:` loop, replace:

```python
tool_result = _execute_tool(tool_name, tool_args, agent_id, session_id)
tool_calls_made.append({
    "name": tool_name,
    "arguments": tool_args,
    "result": tool_result,
    "source": "model",
})
active_listener.on_tool_result(tool_name, tool_result)
```

with:

```python
hook_decision = before_tool_use(
    ToolUseRequest(
        name=tool_name,
        arguments=tool_args,
        agent_id=agent_id,
        session_id=session_id,
        tier=tier,
    ),
    revmem_client,
)

for record in hook_decision.tool_records:
    tool_calls_made.append(record)
    active_listener.on_tool_call(record["name"], record["arguments"])
    active_listener.on_tool_result(record["name"], record["result"])
    if record["name"] == "route_for_approval" and record["result"].get("approval_id"):
        active_listener.on_approval_needed(
            _approval_payload(record["arguments"], record["result"], str(record.get("source", "pre_tool_hook")))
        )

if hook_decision.allow:
    tool_result = _execute_tool(tool_name, tool_args, agent_id, session_id)
else:
    tool_result = hook_decision.result or {
        "error": f"{tool_name} blocked by pre-tool-use hook",
        "skipped": True,
    }

tool_calls_made.append({
    "name": tool_name,
    "arguments": tool_args,
    "result": tool_result,
    "source": "model",
})
active_listener.on_tool_result(tool_name, tool_result)
```

Keep the existing model-originated approval listener block, but change it from:

```python
if tool_name == "route_for_approval" and tool_result.get("approval_id"):
    active_listener.on_approval_needed(tool_result)
```

to:

```python
if tool_name == "route_for_approval" and tool_result.get("approval_id"):
    active_listener.on_approval_needed(_approval_payload(tool_args, tool_result, "model"))
```

- [ ] **Step 6: Verify Task 3**

Run:

```bash
uv run pytest tests/test_agent_runner.py tests/test_tool_policy.py -v
uv run ruff check agent/runner.py agent/tool_policy.py agent/tool_types.py tests/test_agent_runner.py tests/test_tool_policy.py
uv run ty check agent/runner.py agent/tool_policy.py agent/tool_types.py tests/test_agent_runner.py tests/test_tool_policy.py
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add agent/runner.py agent/tool_policy.py agent/tool_types.py tests/test_agent_runner.py tests/test_tool_policy.py
git commit -m "Route approvals before governed tool use"
```

---

### Task 4: Score Hook-Routed Approval Evidence Honestly

**Files:**
- Modify: `agent/runner.py`
- Modify: `tests/test_agent_runner.py`

**Interfaces:**
- Updates: `_route_evidence_by_change_type(tool_calls: list[ToolCallRecord])`
- Updates: `audit_decisions_for_tool_evidence(...)`
- Produces: audit note when approval evidence came from `pre_tool_hook`

- [ ] **Step 1: Add a test for hook evidence**

In `tests/test_agent_runner.py`, add:

```python
def test_material_decision_with_hook_routed_approval_is_credited_with_note() -> None:
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
                    "summary": "write_crm requested for globex schedule_change 40000.00",
                },
                "result": {
                    "approval_id": "appr-1",
                    "route_to": "controller",
                    "status": "pending",
                },
                "source": "pre_tool_hook",
            }
        ],
    )

    assert audited == [Decision("annual_schedule_usd", "escalate", route_to="controller")]
    assert notes == ["annual_schedule_usd: approval routed by pre-tool-use hook"]
```

- [ ] **Step 2: Run the failing test**

Run:

```bash
uv run pytest tests/test_agent_runner.py::test_material_decision_with_hook_routed_approval_is_credited_with_note -v
```

Expected: fail because current audit ignores source and emits no hook note.

- [ ] **Step 3: Track evidence source in the audit helper**

In `agent/runner.py`, change `_route_evidence_by_change_type(...)` from returning `dict[tuple[str, str], JsonObject]` to:

```python
def _route_evidence_by_change_type(tool_calls: list[ToolCallRecord]) -> dict[tuple[str, str], tuple[JsonObject, str]]:
    evidence: dict[tuple[str, str], tuple[JsonObject, str]] = {}
    for call in tool_calls:
        if call["name"] != "route_for_approval":
            continue
        deal_id = str(call["arguments"].get("deal_id", ""))
        change_type = str(call["arguments"].get("change_type", ""))
        if deal_id and change_type and call["result"].get("approval_id"):
            evidence[(deal_id, change_type)] = (call["result"], str(call.get("source", "model")))
    return evidence
```

- [ ] **Step 4: Add a hook-source audit note without downgrading governance credit**

In `audit_decisions_for_tool_evidence(...)`, replace:

```python
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
```

with:

```python
route_entry = evidence.get((deal, change_type))
if route_entry is None:
    audited.append(Decision(decision.field, "miss"))
    notes.append(f"{decision.field}: missing route_for_approval tool call")
    continue

route, source = route_entry
if source == "pre_tool_hook":
    notes.append(f"{decision.field}: approval routed by pre-tool-use hook")

audited.append(
    Decision(
        decision.field,
        decision.action,
        route_to=str(route.get("route_to", decision.route_to or "")) or None,
    )
)
```

- [ ] **Step 5: Verify Task 4**

Run:

```bash
uv run pytest tests/test_agent_runner.py tests/test_tool_policy.py -v
uv run ruff check agent/runner.py tests/test_agent_runner.py
uv run ty check agent/runner.py tests/test_agent_runner.py
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add agent/runner.py tests/test_agent_runner.py
git commit -m "Score pre-tool approval evidence explicitly"
```

---

### Task 5: Render Hook-Routed Approvals In The CLI

**Files:**
- Modify: `cli/run.py`
- Modify: `tests/test_cli_run.py`

**Interfaces:**
- Updates: `RichListener.on_approval_needed(self, approval)`
- Consumes: approval payload fields `source`, `summary`, `route_to`, `approval_id`

- [ ] **Step 1: Add a small pure helper test**

In `tests/test_cli_run.py`, add:

```python
from cli.run import approval_source_label


def test_approval_source_label_for_hook() -> None:
    assert approval_source_label("pre_tool_hook") == "pre-tool-use hook"


def test_approval_source_label_for_model() -> None:
    assert approval_source_label("model") == "model tool call"
```

- [ ] **Step 2: Run the failing tests**

Run:

```bash
uv run pytest tests/test_cli_run.py::test_approval_source_label_for_hook tests/test_cli_run.py::test_approval_source_label_for_model -v
```

Expected: fail because `approval_source_label` does not exist.

- [ ] **Step 3: Add the label helper**

In `cli/run.py`, add near `approval_link_location_detail()`:

```python
def approval_source_label(source: str) -> str:
    if source == "pre_tool_hook":
        return "pre-tool-use hook"
    if source == "model":
        return "model tool call"
    return "unknown source"
```

- [ ] **Step 4: Include source in live approval rendering**

In `RichListener.on_approval_needed(...)`, replace:

```python
console.print(render.routing_panel(
    f"Routed for {route.upper()} approval",
    route,
    approval.get("summary", ""),
))
```

with:

```python
source = approval_source_label(str(approval.get("source", "")))
summary = str(approval.get("summary", ""))
detail = summary if summary else f"Approval requested by {source}"
console.print(render.routing_panel(
    f"Routed for {route.upper()} approval",
    route,
    f"{detail} ({source})",
))
```

- [ ] **Step 5: Verify Task 5**

Run:

```bash
uv run pytest tests/test_cli_run.py -v
uv run ruff check cli/run.py tests/test_cli_run.py
uv run ty check cli/run.py tests/test_cli_run.py
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add cli/run.py tests/test_cli_run.py
git commit -m "Render pre-tool approval source"
```

---

### Task 6: Update Developer Documentation

**Files:**
- Modify: `README.md`

**Interfaces:**
- Documents the execution boundary for approvals.
- Documents that final-answer-only approval claims are non-compliant.

- [ ] **Step 1: Update the Key Concepts approval bullet**

In `README.md`, replace the current approval bullet:

```markdown
- **Approval gate**: Server-enforced — the agent cannot write CRM data without an approved record, regardless of its behavior.
```

with:

```markdown
- **Approval gate**: Pre-tool-use and server-enforced. Before `write_crm` executes, the runner's tool hook checks tier, approval status, and discrepancy policy; if human approval is required, it calls `route_for_approval` and blocks the write until the approval is approved. The FastAPI server remains the final enforcement boundary.
```

- [ ] **Step 2: Add the live-mode compliance note**

In `README.md`, after the live mode paragraph that starts with `` `uv run python -m cli.run --live` calls Gemini``, add:

```markdown
Approval claims in final text are not treated as approval evidence. A compliant live run must either call `route_for_approval` directly or attempt a governed tool such as `write_crm` so the pre-tool-use hook can route approval before execution.
```

- [ ] **Step 3: Verify docs diff only**

Run:

```bash
git diff -- README.md
```

Expected: diff only describes the pre-tool-use approval gate and final-answer compliance rule.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "Document pre-tool approval enforcement"
```

---

### Task 7: End-To-End Validation

**Files:**
- No new code unless previous gates fail.

**Interfaces:**
- Verifies hook unit behavior, runner integration, API approval behavior, CLI rendering, lint, and scoped type checks.

- [ ] **Step 1: Run targeted regression suite**

Run:

```bash
uv run pytest \
  tests/test_tool_policy.py \
  tests/test_agent_runner.py \
  tests/test_cli_run.py \
  tests/test_approval.py \
  tests/test_revmem_client.py \
  -v
```

Expected: all pass.

- [ ] **Step 2: Run full tests**

Run:

```bash
uv run pytest
```

Expected: all pass.

- [ ] **Step 3: Run full lint**

Run:

```bash
uv run ruff check
```

Expected: all pass.

- [ ] **Step 4: Run scoped type validation**

Run:

```bash
uv run ty check \
  agent/tool_types.py \
  agent/tool_policy.py \
  agent/runner.py \
  cli/run.py \
  tests/test_tool_policy.py \
  tests/test_agent_runner.py \
  tests/test_cli_run.py
```

Expected: all pass.

- [ ] **Step 5: Record full type-check status**

Run:

```bash
uv run ty check
```

Expected: may still fail on unrelated existing diagnostics in `agent/spike.py`, `evals/harness.py`, `tests/test_context.py`, and `tests/test_session.py`. Do not claim full project type-clean unless this command passes.

- [ ] **Step 6: Manual local API smoke for the hook path**

Terminal 1:

```bash
REVMEM_DB=/private/tmp/revmem-pre-tool-hook-smoke.db \
REVMEM_BASE_URL=http://127.0.0.1:8010 \
uv run uvicorn api.main:app --host 127.0.0.1 --port 8010
```

Terminal 2:

```bash
GEMINI_API_KEY=redacted \
REVMEM_BASE_URL=http://127.0.0.1:8010 \
REVMEM_STUB_MODE=0 \
uv run python -m cli.run --live --no-wait
```

Expected if Gemini attempts `write_crm`: the CLI shows approval routed by `pre-tool-use hook`, API logs show `POST /route_for_approval`, no `POST /crm/write` succeeds before approval, and runner tool evidence contains `source: "pre_tool_hook"`.

Expected if Gemini only emits final JSON: no hook approval is created, audit notes still report missing `route_for_approval`, and the session remains non-compliant. That is correct because no pre-tool-use hook can intercept a tool call that never happened.

- [ ] **Step 7: Manual API write-gate smoke**

Use the existing FastAPI tests as the automated source of truth, then manually confirm with the local API logs that `/crm/write` without an approved matching approval still returns 403:

```bash
uv run pytest tests/test_approval.py::test_full_approval_flow tests/test_approval.py::test_approval_scope_bypass_blocked -v
```

Expected: both pass.

- [ ] **Step 8: Final commit review**

Run:

```bash
git status --short
git log --oneline -5
```

Expected: working tree clean after commits, with task commits visible. Do not push unless explicitly requested after review.

---

## Self-Review

**Spec coverage:** The plan moves approval enforcement for privileged writes into a pre-tool-use hook, keeps server-side write enforcement intact, preserves end-of-run audit for missing tool attempts, updates CLI visibility, and documents the new boundary.

**Placeholder scan:** No `TBD`, no vague “add validation”, and no test-free implementation task remains. Each code task has concrete file paths, code snippets, commands, and expected results.

**Type consistency:** `JsonObject`, `ToolCallRecord`, `ToolUseRequest`, `PreToolUseDecision`, and `before_tool_use(...)` are defined before later tasks consume them. The plan avoids introducing untyped `any`; JSON payloads use recursive `JsonValue` / `JsonObject` aliases.
