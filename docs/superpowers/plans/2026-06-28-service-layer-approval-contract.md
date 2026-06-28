# Service-Layer Approval Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Define approval requirements at the route/method level, including whether approval is required, which approvers are OR vs AND, and which approvals depend on other approvals.

**Architecture:** Add a method approval policy layer that maps service methods like `crm.write` and `policy.update` to declarative approval graphs. API routes call this gate before side effects; the gate either allows execution or returns a structured approval request with approver tasks, join semantics, and dependency metadata. Agent code remains only a client of the service contract and records approval evidence returned by service methods.

**Tech Stack:** Python 3.13, FastAPI, Pydantic, SQLite, Google GenAI / Antigravity interactions, Rich CLI, pytest, Ruff, ty.

## Global Constraints

- Do not add a caller-controlled `requires_approval` request parameter. Approval requirement is computed from route/method policy.
- Approval policy must not be hard-coded only in `/crm/write`; every side-effect route must have an explicit method policy, even if that policy is `approval_required=False`.
- Method policies must express approver join semantics: `any` means one approver satisfies the request; `all` means every required approver must approve.
- Method policies must express approval dependencies, such as `cco` depending on `cfo`.
- A service method must not perform its side effect while its approval request is pending, rejected, missing, mismatched, or dependency-blocked.
- Keep human approval tokens out of agent-visible JSON responses.
- Keep individual approval links token-gated; request/status polling endpoints may expose IDs and statuses but not tokens.
- Keep `/route_for_approval` for explicit approval creation, but implement it through the same method policy machinery rather than a one-off approval shape.
- Remove `agent/tool_policy.py` from the runtime path. If a future agent harness needs hooks, it should live outside the service contract.
- No network-dependent automated tests. Live Gemini/API checks are optional manual smoke gates only.
- Use `uv run` for every Python command.
- Run `uv run ruff check` and scoped `uv run ty check` for every edited Python file. Full `uv run ty check` currently has unrelated existing failures; record the result without claiming full type-clean unless it passes.
- Do not delete branches automatically when pushing.

---

## File Structure

- Create `core/approval_policy.py`: method-level approval registry, approver graph types, OR/AND join evaluation, and dependency checks.
- Modify `core/models.py`: extend approval models for grouped approval requests, method keys, join semantics, step IDs, and dependencies.
- Modify `core/database.py`: persist grouped approval tasks and query them by request ID.
- Modify `api/routes.py`: route all side-effect endpoints through the method approval gate before mutation.
- Create `api/approval_gate.py`: service helper that creates approval requests, computes aggregate request status, and returns structured approval-required payloads.
- Modify `agent/revmem_client.py`: document and stub the method approval response contract.
- Modify `agent/tools.py`, `agent/prompts.py`, and `agent/templates/skill_md.py`: expose `approval_request_id` and service-returned `approval_required` semantics.
- Modify `agent/runner.py`: remove runner-owned pre-tool approval routing and record service-returned approval evidence.
- Modify `agent/tool_types.py`: remove `pre_tool_hook` source typing.
- Delete `agent/tool_policy.py` and `tests/test_tool_policy.py`.
- Modify `tests/test_governance.py`, `tests/test_approval.py`, `tests/test_api.py`, `tests/test_revmem_client.py`, `tests/test_agent_runner.py`, `tests/test_cli_run.py`, and `tests/test_agent_tools.py`.
- Modify `README.md` and mark `docs/superpowers/plans/2026-06-28-pre-tool-use-approval-hook.md` as superseded.
- Do not modify `AGENTS.md`; this repo currently has no top-level `AGENTS.md`.

---

### Task 1: Add Route/Method Approval Policy Types

**Files:**
- Create: `core/approval_policy.py`
- Modify: `tests/test_governance.py`

**Interfaces:**
- Produces: `ApprovalJoin`
- Produces: `ApprovalStep`
- Produces: `MethodApprovalPlan`
- Produces: `approval_plan_for_method(method: str, context: Mapping[str, Any]) -> MethodApprovalPlan`
- Produces: `approval_request_satisfied(join: str, approvals: Sequence[Mapping[str, str]]) -> bool`
- Produces: `dependencies_satisfied(step_id: str, approvals: Sequence[Mapping[str, str]]) -> bool`

- [ ] **Step 1: Write failing tests for method-level policy**

Add to `tests/test_governance.py`:

```python
from core.approval_policy import (
    ApprovalJoin,
    ApprovalStatus,
    approval_plan_for_method,
    approval_request_satisfied,
    dependencies_satisfied,
)


def test_crm_write_schedule_change_requires_controller_method_approval() -> None:
    plan = approval_plan_for_method(
        "crm.write",
        {"tier": "analyst", "discrepancy": {"deal_id": "globex", "amount_usd": 40000, "change_type": "schedule_change"}},
    )

    assert plan.required is True
    assert plan.join == ApprovalJoin.ALL
    assert [(step.step_id, step.role, step.depends_on) for step in plan.steps] == [
        ("controller", "controller", ()),
    ]


def test_crm_write_discount_requires_dependent_cfo_then_cco_approvals() -> None:
    plan = approval_plan_for_method(
        "crm.write",
        {"tier": "analyst", "discrepancy": {"deal_id": "globex", "amount_usd": 0, "change_type": "discount_over_authority"}},
    )

    assert plan.required is True
    assert plan.join == ApprovalJoin.ALL
    assert [(step.step_id, step.role, step.depends_on) for step in plan.steps] == [
        ("cfo", "cfo", ()),
        ("cco", "cco", ("cfo",)),
    ]


def test_policy_update_allows_any_finance_admin_or_controller() -> None:
    plan = approval_plan_for_method("policy.update", {"tier": "analyst"})

    assert plan.required is True
    assert plan.join == ApprovalJoin.ANY
    assert {step.role for step in plan.steps} == {"finance_admin", "controller"}


def test_non_sensitive_methods_are_explicitly_no_approval() -> None:
    plan = approval_plan_for_method("sessions.complete", {"tier": "observer"})

    assert plan.required is False
    assert plan.steps == ()


def test_approval_join_and_dependencies_are_evaluated() -> None:
    approvals = [
        {"step_id": "cfo", "status": ApprovalStatus.APPROVED},
        {"step_id": "cco", "status": ApprovalStatus.PENDING},
    ]

    assert approval_request_satisfied(ApprovalJoin.ALL, approvals) is False
    assert approval_request_satisfied(ApprovalJoin.ANY, approvals) is True
    assert dependencies_satisfied("cco", approvals) is True
    assert dependencies_satisfied("cfo", approvals) is True

    blocked = [{"step_id": "cfo", "status": ApprovalStatus.PENDING}]
    assert dependencies_satisfied("cco", blocked) is False
```

- [ ] **Step 2: Run the failing policy tests**

Run:

```bash
uv run pytest tests/test_governance.py::test_crm_write_schedule_change_requires_controller_method_approval tests/test_governance.py::test_crm_write_discount_requires_dependent_cfo_then_cco_approvals tests/test_governance.py::test_policy_update_allows_any_finance_admin_or_controller tests/test_governance.py::test_non_sensitive_methods_are_explicitly_no_approval tests/test_governance.py::test_approval_join_and_dependencies_are_evaluated -v
```

Expected: fail because `core.approval_policy` does not exist.

- [ ] **Step 3: Implement the method approval policy module**

Create `core/approval_policy.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from core.models import ApprovalStatus, PermissionTier


class ApprovalJoin:
    ANY = "any"
    ALL = "all"


@dataclass(frozen=True)
class ApprovalStep:
    step_id: str
    role: str
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True)
class MethodApprovalPlan:
    method: str
    required: bool
    join: str = ApprovalJoin.ALL
    steps: tuple[ApprovalStep, ...] = ()
    reason: str = ""


NO_APPROVAL_METHODS = {
    "agents.create",
    "sessions.create",
    "sessions.complete",
    "memory.create",
    "approval.route",
    "approval.decide",
}


def _crm_write_plan(context: Mapping[str, Any]) -> MethodApprovalPlan:
    tier = str(context.get("tier", ""))
    discrepancy = context.get("discrepancy", {})
    change_type = discrepancy.get("change_type") if isinstance(discrepancy, Mapping) else None

    if tier == PermissionTier.OBSERVER:
        return MethodApprovalPlan("crm.write", required=False, reason="tier observer cannot write CRM")
    if tier == PermissionTier.AUTONOMOUS and change_type != "discount_over_authority":
        return MethodApprovalPlan("crm.write", required=False, reason="policy-covered autonomous write")
    if change_type == "discount_over_authority":
        return MethodApprovalPlan(
            "crm.write",
            required=True,
            join=ApprovalJoin.ALL,
            steps=(
                ApprovalStep("cfo", "cfo"),
                ApprovalStep("cco", "cco", depends_on=("cfo",)),
            ),
            reason="discount over authority requires CFO then CCO approval",
        )
    return MethodApprovalPlan(
        "crm.write",
        required=True,
        join=ApprovalJoin.ALL,
        steps=(ApprovalStep("controller", "controller"),),
        reason="material CRM write requires controller approval",
    )


def _policy_update_plan(context: Mapping[str, Any]) -> MethodApprovalPlan:
    return MethodApprovalPlan(
        "policy.update",
        required=True,
        join=ApprovalJoin.ANY,
        steps=(
            ApprovalStep("finance_admin", "finance_admin"),
            ApprovalStep("controller", "controller"),
        ),
        reason="policy updates require finance admin or controller approval",
    )


def approval_plan_for_method(method: str, context: Mapping[str, Any]) -> MethodApprovalPlan:
    if method in NO_APPROVAL_METHODS:
        return MethodApprovalPlan(method, required=False, reason="method does not require approval")
    if method == "crm.write":
        return _crm_write_plan(context)
    if method == "policy.update":
        return _policy_update_plan(context)
    raise KeyError(f"no approval policy registered for method {method}")


def approval_request_satisfied(join: str, approvals: Sequence[Mapping[str, str]]) -> bool:
    statuses = [approval.get("status") for approval in approvals]
    if not statuses:
        return False
    if join == ApprovalJoin.ANY:
        return ApprovalStatus.APPROVED in statuses
    return all(status == ApprovalStatus.APPROVED for status in statuses)


def dependencies_satisfied(step_id: str, approvals: Sequence[Mapping[str, str]]) -> bool:
    dependencies: tuple[str, ...] = ()
    for approval in approvals:
        if approval.get("step_id") == step_id:
            raw = approval.get("depends_on", "")
            dependencies = tuple(part for part in raw.split(",") if part)
            break
    by_step = {approval.get("step_id", ""): approval.get("status", "") for approval in approvals}
    return all(by_step.get(dep) == ApprovalStatus.APPROVED for dep in dependencies)
```

- [ ] **Step 4: Verify Task 1**

Run:

```bash
uv run pytest tests/test_governance.py -v
uv run ruff check core/approval_policy.py tests/test_governance.py
uv run ty check core/approval_policy.py tests/test_governance.py
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add core/approval_policy.py tests/test_governance.py
git commit -m "Define method-level approval policies"
```

---

### Task 2: Persist Approval Request Graphs

**Files:**
- Modify: `core/models.py`
- Modify: `core/database.py`
- Modify: `tests/test_database.py`

**Interfaces:**
- Extends: `Approval` with `request_id`, `method`, `join`, `step_id`, and `depends_on`
- Produces: `database.insert_approvals(conn, approvals: list[Approval]) -> None`
- Produces: `database.list_approvals_for_request(conn, request_id: str) -> list[Approval]`
- Keeps: `database.get_approval(conn, approval_id: str) -> Approval | None`

- [ ] **Step 1: Add database tests for grouped approvals**

Add to `tests/test_database.py`:

```python
from core.models import Approval, ApprovalStatus


def test_grouped_approvals_round_trip(conn):
    approvals = [
        Approval(
            request_id="req-1",
            method="crm.write",
            join="all",
            step_id="cfo",
            deal_id="globex",
            discrepancy={"deal_id": "globex", "change_type": "discount_over_authority"},
            approver_role="cfo",
        ),
        Approval(
            request_id="req-1",
            method="crm.write",
            join="all",
            step_id="cco",
            depends_on=["cfo"],
            deal_id="globex",
            discrepancy={"deal_id": "globex", "change_type": "discount_over_authority"},
            approver_role="cco",
        ),
    ]

    database.insert_approvals(conn, approvals)

    got = database.list_approvals_for_request(conn, "req-1")
    assert [approval.step_id for approval in got] == ["cfo", "cco"]
    assert got[1].depends_on == ["cfo"]
    assert got[0].status == ApprovalStatus.PENDING
```

- [ ] **Step 2: Run the failing database test**

Run:

```bash
uv run pytest tests/test_database.py::test_grouped_approvals_round_trip -v
```

Expected: fail because `Approval` and `database` do not support grouped approvals yet.

- [ ] **Step 3: Extend the approval model**

In `core/models.py`, update `Approval`:

```python
class Approval(BaseModel):
    id: str = Field(default_factory=_uuid)
    request_id: str = Field(default_factory=_uuid)
    method: str = "approval.route"
    join: str = "all"
    step_id: str = ""
    depends_on: list[str] = Field(default_factory=list)
    deal_id: str
    discrepancy: dict[str, Any]
    approver_role: str
    status: str = ApprovalStatus.PENDING
    token: str = Field(default_factory=_uuid)
    created_at: datetime = Field(default_factory=_now)
    decided_at: datetime | None = None
```

- [ ] **Step 4: Extend the approvals table and row mapping**

In `core/database.py`, update the approvals table creation to include:

```sql
request_id TEXT NOT NULL,
method TEXT NOT NULL,
join_mode TEXT NOT NULL,
step_id TEXT NOT NULL,
depends_on TEXT NOT NULL,
```

Update `insert_approval(...)` to write the new fields. Add:

```python
def insert_approvals(conn: sqlite3.Connection, approvals: list[Approval]) -> None:
    for approval in approvals:
        insert_approval(conn, approval)


def list_approvals_for_request(conn: sqlite3.Connection, request_id: str) -> list[Approval]:
    rows = conn.execute(
        "SELECT * FROM approvals WHERE request_id=? ORDER BY created_at, step_id",
        (request_id,),
    ).fetchall()
    return [_approval_from_row(row) for row in rows]
```

Extract the existing `get_approval(...)` row conversion into:

```python
def _approval_from_row(row: sqlite3.Row) -> Approval:
    return Approval(
        id=row["id"],
        request_id=row["request_id"],
        method=row["method"],
        join=row["join_mode"],
        step_id=row["step_id"],
        depends_on=json.loads(row["depends_on"]),
        deal_id=row["deal_id"],
        discrepancy=json.loads(row["discrepancy"]),
        approver_role=row["approver_role"],
        status=row["status"],
        token=row["token"],
        created_at=datetime.fromisoformat(row["created_at"]),
        decided_at=_dt(row["decided_at"]),
    )
```

- [ ] **Step 5: Verify Task 2**

Run:

```bash
uv run pytest tests/test_database.py -v
uv run ruff check core/models.py core/database.py tests/test_database.py
uv run ty check core/models.py core/database.py tests/test_database.py
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add core/models.py core/database.py tests/test_database.py
git commit -m "Persist grouped approval requests"
```

---

### Task 3: Add A Reusable API Approval Gate

**Files:**
- Create: `api/approval_gate.py`
- Modify: `tests/test_approval.py`

**Interfaces:**
- Produces: `ensure_method_approved(conn, method: str, context: dict[str, Any], request_id: str | None = None) -> ApprovalGateResult`
- Produces: `ApprovalGateResult.allowed`
- Produces: `ApprovalGateResult.payload`
- Produces: aggregate request status from grouped approval rows

- [ ] **Step 1: Add gate unit tests**

Add to `tests/test_approval.py`:

```python
from api.approval_gate import ensure_method_approved


def test_gate_creates_all_approval_request_with_dependencies(client):
    conn = client.app.state.conn
    result = ensure_method_approved(
        conn,
        "crm.write",
        {
            "tier": PermissionTier.ANALYST,
            "deal_id": "globex",
            "discrepancy": {"deal_id": "globex", "amount_usd": 0, "change_type": "discount_over_authority"},
        },
    )

    assert result.allowed is False
    assert result.payload["approval_required"] is True
    assert result.payload["approval_join"] == "all"
    assert [approval["role"] for approval in result.payload["approvals"]] == ["cfo", "cco"]
    assert result.payload["approvals"][1]["depends_on"] == ["cfo"]


def test_gate_allows_any_request_after_one_approval(client):
    conn = client.app.state.conn
    result = ensure_method_approved(conn, "policy.update", {"tier": PermissionTier.ANALYST})
    request_id = result.payload["approval_request_id"]
    first = database.list_approvals_for_request(conn, request_id)[0]
    first.status = ApprovalStatus.APPROVED
    database.update_approval(conn, first)

    allowed = ensure_method_approved(conn, "policy.update", {"tier": PermissionTier.ANALYST}, request_id)

    assert allowed.allowed is True
    assert allowed.payload["approval_required"] is False
```

- [ ] **Step 2: Run the failing gate tests**

Run:

```bash
uv run pytest tests/test_approval.py::test_gate_creates_all_approval_request_with_dependencies tests/test_approval.py::test_gate_allows_any_request_after_one_approval -v
```

Expected: fail because `api.approval_gate` does not exist.

- [ ] **Step 3: Implement the gate helper**

Create `api/approval_gate.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from core import approval_policy, database
from core.models import Approval, ApprovalStatus


@dataclass(frozen=True)
class ApprovalGateResult:
    allowed: bool
    payload: dict[str, Any]


def _approval_payload(approvals: list[Approval], reason: str) -> dict[str, Any]:
    request_id = approvals[0].request_id
    return {
        "ok": False,
        "decision": "needs_approval",
        "approval_required": True,
        "approval_request_id": request_id,
        "approval_join": approvals[0].join,
        "approval_status": "pending",
        "reason": reason,
        "approvals": [
            {
                "approval_id": approval.id,
                "step_id": approval.step_id,
                "role": approval.approver_role,
                "status": approval.status,
                "depends_on": approval.depends_on,
            }
            for approval in approvals
        ],
    }


def _rows_for_policy(method: str, context: dict[str, Any]) -> list[Approval]:
    plan = approval_policy.approval_plan_for_method(method, context)
    request_id = str(uuid4())
    deal_id = str(context.get("deal_id", ""))
    discrepancy = context.get("discrepancy", {})
    if not isinstance(discrepancy, dict):
        discrepancy = {}
    return [
        Approval(
            request_id=request_id,
            method=method,
            join=plan.join,
            step_id=step.step_id,
            depends_on=list(step.depends_on),
            deal_id=deal_id,
            discrepancy=discrepancy,
            approver_role=step.role,
        )
        for step in plan.steps
    ]


def _approved_payload(request_id: str) -> dict[str, Any]:
    return {
        "ok": True,
        "decision": "allow",
        "approval_required": False,
        "approval_request_id": request_id,
    }


def ensure_method_approved(
    conn,
    method: str,
    context: dict[str, Any],
    request_id: str | None = None,
) -> ApprovalGateResult:
    plan = approval_policy.approval_plan_for_method(method, context)
    if not plan.required:
        return ApprovalGateResult(True, {"ok": True, "decision": "allow", "approval_required": False})

    if request_id:
        approvals = database.list_approvals_for_request(conn, request_id)
        if not approvals or any(approval.method != method for approval in approvals):
            return ApprovalGateResult(False, {"ok": False, "decision": "deny", "approval_required": False, "reason": "approval request mismatch"})
        rows = [
            {
                "step_id": approval.step_id,
                "status": approval.status,
                "depends_on": ",".join(approval.depends_on),
            }
            for approval in approvals
        ]
        if approval_policy.approval_request_satisfied(approvals[0].join, rows):
            return ApprovalGateResult(True, _approved_payload(request_id))
        return ApprovalGateResult(False, _approval_payload(approvals, plan.reason))

    approvals = _rows_for_policy(method, context)
    database.insert_approvals(conn, approvals)
    return ApprovalGateResult(False, _approval_payload(approvals, plan.reason))
```

- [ ] **Step 4: Verify Task 3**

Run:

```bash
uv run pytest tests/test_approval.py::test_gate_creates_all_approval_request_with_dependencies tests/test_approval.py::test_gate_allows_any_request_after_one_approval -v
uv run ruff check api/approval_gate.py tests/test_approval.py
uv run ty check api/approval_gate.py tests/test_approval.py
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add api/approval_gate.py tests/test_approval.py
git commit -m "Add reusable method approval gate"
```

---

### Task 4: Apply Method Approval Policy To Multiple Routes

**Files:**
- Modify: `api/routes.py`
- Modify: `tests/test_approval.py`
- Modify: `tests/test_api.py`

**Interfaces:**
- Updates: `CrmWrite.approval_request_id`
- Updates: `PolicyEdit.approval_request_id`
- Produces: `/approval-requests/{request_id}/status`
- Keeps: `/approvals/{approval_id}/status`

- [ ] **Step 1: Add route-level API tests**

Add to `tests/test_approval.py`:

```python
def test_crm_write_uses_method_policy_request_id_flow(client):
    aid = _make_analyst(client)
    disc = {"deal_id": "acme", "amount_usd": 40000, "change_type": "schedule_change"}
    body = {
        "agent_id": aid,
        "deal_id": "acme",
        "fields": {"annual_schedule_usd": [100000, 150000, 200000]},
        "discrepancy": disc,
    }

    pending = client.post("/crm/write", json=body)

    assert pending.status_code == 202
    payload = pending.json()
    assert payload["approval_required"] is True
    assert payload["approval_request_id"]
    assert payload["approval_join"] == "all"
    assert payload["approvals"][0]["role"] == "controller"
    assert client.get("/crm/acme").json()["annual_schedule_usd"] != [100000, 150000, 200000]


def test_policy_update_uses_any_approval_method_policy(client):
    created = client.post(
        "/route_for_approval",
        json={"deal_id": "acme", "amount_usd": 40000, "change_type": "schedule_change"},
    )
    assert created.status_code == 200

    policy = client.get("/policy").json()[0]
    pending = client.put(
        f"/policy/{policy['id']}",
        json={"route_to": "controller"},
    )

    assert pending.status_code == 202
    payload = pending.json()
    assert payload["approval_required"] is True
    assert payload["approval_join"] == "any"
    assert {approval["role"] for approval in payload["approvals"]} == {"finance_admin", "controller"}
```

Add a dependency test:

```python
def test_dependent_approval_cannot_be_decided_before_parent(client):
    aid = _make_analyst(client)
    body = {
        "agent_id": aid,
        "deal_id": "globex",
        "fields": {"discount_pct": 25},
        "discrepancy": {"deal_id": "globex", "amount_usd": 0, "change_type": "discount_over_authority"},
    }
    pending = client.post("/crm/write", json=body).json()
    cco = next(approval for approval in pending["approvals"] if approval["role"] == "cco")
    approval = database.get_approval(client.app.state.conn, cco["approval_id"])
    assert approval is not None

    response = client.post(
        f"/approvals/{approval.id}/decision",
        data={"decision": "approve", "token": approval.token},
    )

    assert response.status_code == 409
```

- [ ] **Step 2: Run failing route tests**

Run:

```bash
uv run pytest tests/test_approval.py::test_crm_write_uses_method_policy_request_id_flow tests/test_approval.py::test_policy_update_uses_any_approval_method_policy tests/test_approval.py::test_dependent_approval_cannot_be_decided_before_parent -v
```

Expected: fail because routes do not call the method approval gate yet.

- [ ] **Step 3: Update request models**

In `api/routes.py`, change:

```python
class CrmWrite(BaseModel):
    agent_id: str
    deal_id: str
    fields: dict[str, Any]
    discrepancy: dict[str, Any] = {}
    approval_id: str | None = None
```

to:

```python
class CrmWrite(BaseModel):
    agent_id: str
    deal_id: str
    fields: dict[str, Any]
    discrepancy: dict[str, Any] = {}
    approval_request_id: str | None = None
```

Change `PolicyEdit` to:

```python
class PolicyEdit(BaseModel):
    condition: dict[str, Any] | None = None
    route_to: str | None = None
    approval_request_id: str | None = None
```

- [ ] **Step 4: Gate `/crm/write` through method policy**

In `api/routes.py`, import:

```python
from api.approval_gate import ensure_method_approved
```

Inside `write_crm(...)`, before mutation:

```python
    gate = ensure_method_approved(
        conn,
        "crm.write",
        {
            "tier": agent.permission_tier,
            "deal_id": body.deal_id,
            "discrepancy": body.discrepancy,
        },
        body.approval_request_id,
    )
    if not gate.allowed:
        if gate.payload.get("approval_required"):
            response.status_code = status.HTTP_202_ACCEPTED
            return gate.payload
        raise HTTPException(403, str(gate.payload.get("reason", "write not allowed")))
```

Keep the CRM mutation only after this gate.

- [ ] **Step 5: Gate `/policy/{policy_id}` through method policy**

In `update_policy(...)`, before mutation:

```python
    gate = ensure_method_approved(
        conn,
        "policy.update",
        {"tier": "analyst", "policy_id": policy_id},
        body.approval_request_id,
    )
    if not gate.allowed:
        if gate.payload.get("approval_required"):
            response.status_code = status.HTTP_202_ACCEPTED
            return gate.payload
        raise HTTPException(403, str(gate.payload.get("reason", "policy update not allowed")))
```

Change the route signature to accept `response: Response`.

- [ ] **Step 6: Add request-level status endpoint**

Add:

```python
@router.get("/approval-requests/{request_id}/status")
def approval_request_status(request_id: str, request: Request) -> dict[str, Any]:
    approvals = database.list_approvals_for_request(_conn(request), request_id)
    if not approvals:
        raise HTTPException(404, "unknown approval request")
    return {
        "approval_request_id": request_id,
        "approval_join": approvals[0].join,
        "approvals": [
            {
                "approval_id": approval.id,
                "step_id": approval.step_id,
                "role": approval.approver_role,
                "status": approval.status,
                "depends_on": approval.depends_on,
            }
            for approval in approvals
        ],
    }
```

- [ ] **Step 7: Enforce dependency order on approval decisions**

In `approval_decision(...)`, before changing status, load siblings:

```python
    siblings = database.list_approvals_for_request(conn, a.request_id)
    rows = [
        {
            "step_id": approval.step_id,
            "status": approval.status,
            "depends_on": ",".join(approval.depends_on),
        }
        for approval in siblings
    ]
    if not approval_policy.dependencies_satisfied(a.step_id, rows):
        raise HTTPException(409, "approval dependencies are not satisfied")
```

Import `core.approval_policy`.

- [ ] **Step 8: Verify Task 4**

Run:

```bash
uv run pytest tests/test_approval.py tests/test_api.py -v
uv run ruff check api/routes.py tests/test_approval.py tests/test_api.py
uv run ty check api/routes.py tests/test_approval.py tests/test_api.py
```

Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add api/routes.py tests/test_approval.py tests/test_api.py
git commit -m "Apply method approval policy to side-effect routes"
```

---

### Task 5: Update Agent Client And Tool Contract

**Files:**
- Modify: `agent/revmem_client.py`
- Modify: `agent/tools.py`
- Modify: `agent/prompts.py`
- Modify: `agent/templates/skill_md.py`
- Modify: `tests/test_revmem_client.py`
- Modify: `tests/test_agent_tools.py`

**Interfaces:**
- Updates: `write_crm(..., approval_request_id: str | None = None) -> JsonObject`
- Produces: `get_approval_request_status(request_id: str) -> JsonObject`
- Updates: tool schema to use `approval_request_id`
- Keeps: no `requires_approval` parameter

- [ ] **Step 1: Add client/tool tests**

Add to `tests/test_revmem_client.py`:

```python
def test_write_crm_contract_uses_request_id_not_requires_approval() -> None:
    from agent.tools import WRITE_CRM

    properties = WRITE_CRM["parameters"]["properties"]

    assert "approval_request_id" in properties
    assert "approval_id" not in properties
    assert "requires_approval" not in properties
```

Add:

```python
def test_get_approval_request_status_calls_request_endpoint(monkeypatch):
    calls = []

    def fake_api_call(method, path, body=None):
        calls.append((method, path, body))
        return {"approval_request_id": "req-1", "approval_join": "all", "approvals": []}

    monkeypatch.setattr(client, "_api_call", fake_api_call)

    result = client.get_approval_request_status("req-1")

    assert result["approval_request_id"] == "req-1"
    assert calls == [("GET", "/approval-requests/req-1/status", None)]
```

- [ ] **Step 2: Run failing client/tool tests**

Run:

```bash
uv run pytest tests/test_revmem_client.py::test_write_crm_contract_uses_request_id_not_requires_approval tests/test_revmem_client.py::test_get_approval_request_status_calls_request_endpoint -v
```

Expected: fail until client/tool schema are updated.

- [ ] **Step 3: Update client methods**

In `agent/revmem_client.py`, change `write_crm(...)` signature:

```python
def write_crm(
    agent_id: str,
    deal_id: str,
    fields: JsonObject,
    discrepancy: JsonObject | None = None,
    approval_request_id: str | None = None,
) -> JsonObject:
```

Send:

```python
{
    "agent_id": agent_id,
    "deal_id": deal_id,
    "fields": fields,
    "discrepancy": discrepancy or {},
    "approval_request_id": approval_request_id,
}
```

Add:

```python
def get_approval_request_status(request_id: str) -> JsonObject:
    path = f"/approval-requests/{quote(request_id)}/status"
    return _expect_object(_api_call("GET", path), path)
```

Update the stub `/crm/write` response to include:

```python
"approval_required": False,
"approval_request_id": None,
```

- [ ] **Step 4: Update tool schema and prompts**

In `agent/tools.py`, replace `approval_id` in `WRITE_CRM` with:

```python
"approval_request_id": {"type": "string"},
```

Add a tool definition for `get_approval_request_status` or update the existing approval-status tool to request an approval request ID:

```python
GET_APPROVAL_REQUEST_STATUS: ToolDefinition = {
    "type": "function",
    "name": "get_approval_request_status",
    "description": "Poll an approval request. Does not return approval tokens.",
    "parameters": {
        "type": "object",
        "properties": {"approval_request_id": {"type": "string"}},
        "required": ["approval_request_id"],
    },
}
```

Update `get_tools_for_tier(...)` to expose this tool where `get_approval_status` was previously exposed.

In `agent/prompts.py`, replace approval polling instructions with:

```python
        "6. To request a side effect, call the relevant service tool. The service will either "
        "perform it or return approval_required with approval_request_id and approver state.\n"
        "7. If a tool returns approval_required, poll get_approval_request_status. Retry the "
        "same service method with approval_request_id only after the request is approved.\n"
```

- [ ] **Step 5: Verify Task 5**

Run:

```bash
uv run pytest tests/test_revmem_client.py tests/test_agent_tools.py -v
uv run ruff check agent/revmem_client.py agent/tools.py agent/prompts.py agent/templates/skill_md.py tests/test_revmem_client.py tests/test_agent_tools.py
uv run ty check agent/revmem_client.py agent/tools.py agent/prompts.py agent/templates/skill_md.py tests/test_revmem_client.py tests/test_agent_tools.py
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add agent/revmem_client.py agent/tools.py agent/prompts.py agent/templates/skill_md.py tests/test_revmem_client.py tests/test_agent_tools.py
git commit -m "Expose method approval requests to agent clients"
```

---

### Task 6: Remove Runner-Owned Approval Routing

**Files:**
- Delete: `agent/tool_policy.py`
- Delete: `tests/test_tool_policy.py`
- Modify: `agent/tool_types.py`
- Modify: `agent/runner.py`
- Modify: `tests/test_agent_runner.py`
- Modify: `cli/run.py`
- Modify: `tests/test_cli_run.py`

**Interfaces:**
- Removes: `before_tool_use(...)`
- Removes: `ToolUseRequest`
- Produces: service-returned approval evidence from any method result with `approval_required=True`
- Updates: `approval_source_label("service_method_contract") -> "service method contract"`

- [ ] **Step 1: Replace runner hook regression with service method evidence regression**

In `tests/test_agent_runner.py`, replace `test_run_session_routes_approval_in_pre_tool_hook(...)` with a test named:

```python
def test_run_session_records_service_method_approval_without_runner_routing(monkeypatch) -> None:
```

The fake model should call `write_crm`. Monkeypatch `agent.runner.revmem_client.write_crm` to return:

```python
{
    "ok": False,
    "decision": "needs_approval",
    "approval_required": True,
    "approval_request_id": "req-1",
    "approval_join": "all",
    "approval_status": "pending",
    "approvals": [{"approval_id": "appr-1", "step_id": "controller", "role": "controller", "status": "pending", "depends_on": []}],
    "reason": "material CRM write requires controller approval",
}
```

Assert:

```python
assert route_calls == []
assert result["approvals_routed"][0]["approval_request_id"] == "req-1"
assert result["approvals_routed"][0]["source"] == "service_method_contract"
assert fake_client.interactions.function_results[0][0]["result"]["approval_required"] is True
```

- [ ] **Step 2: Update audit helper expectations**

Add:

```python
def test_material_decision_with_service_method_approval_is_credited_with_note() -> None:
    audited, notes = runner.audit_decisions_for_tool_evidence(
        deal="globex",
        decisions=[Decision("annual_schedule_usd", "escalate", route_to="controller")],
        gold=[_gold_schedule()],
        tool_calls=[
            {
                "name": "write_crm",
                "arguments": {
                    "deal_id": "globex",
                    "discrepancy": {"deal_id": "globex", "amount_usd": 40000.0, "change_type": "schedule_change"},
                },
                "result": {
                    "approval_required": True,
                    "approval_request_id": "req-1",
                    "approvals": [{"role": "controller", "status": "pending"}],
                },
                "source": "model",
            }
        ],
    )

    assert audited == [Decision("annual_schedule_usd", "escalate", route_to="controller")]
    assert notes == ["annual_schedule_usd: approval routed by service method contract"]
```

- [ ] **Step 3: Run failing runner tests**

Run:

```bash
uv run pytest tests/test_agent_runner.py::test_run_session_records_service_method_approval_without_runner_routing tests/test_agent_runner.py::test_material_decision_with_service_method_approval_is_credited_with_note -v
```

Expected: fail until the runner stops using the hook and starts reading service method evidence.

- [ ] **Step 4: Remove hook imports and hook execution**

In `agent/runner.py`, delete:

```python
from agent.tool_policy import ToolUseRequest, before_tool_use
```

Delete `_RevMemApprovalClient`.

Delete `approval_client = _RevMemApprovalClient()`.

Inside the tool loop, directly execute:

```python
tool_started = time.perf_counter()
tool_result = _execute_tool(tool_name, tool_args, agent_id, session_id)
_notify(active_listener, "on_tool_timing", tool_name, time.perf_counter() - tool_started)
tool_record: ToolCallRecord = {
    "name": tool_name,
    "arguments": tool_args,
    "result": tool_result,
    "source": "model",
}
tool_calls_made.append(tool_record)
_notify(active_listener, "on_tool_result", tool_name, tool_result)
```

- [ ] **Step 5: Add generic service approval evidence extraction**

In `agent/runner.py`, add:

```python
def _tool_call_approval_payload(call: ToolCallRecord) -> JsonObject | None:
    if call["name"] == "route_for_approval" and call["result"].get("approval_id"):
        return _approval_payload(call["arguments"], call["result"], "model")
    if call["result"].get("approval_required") and call["result"].get("approval_request_id"):
        return _approval_payload(call["arguments"], call["result"], "service_method_contract")
    return None
```

Use this helper for `on_approval_needed`, `approvals_routed`, and `_route_evidence_by_change_type(...)`.

- [ ] **Step 6: Remove obsolete hook files and typing**

Delete with `apply_patch`:

```text
agent/tool_policy.py
tests/test_tool_policy.py
```

In `agent/tool_types.py`, remove `"pre_tool_hook"` from `ToolCallSource`.

In `cli/run.py`, update:

```python
def approval_source_label(source: str) -> str:
    if source == "service_method_contract":
        return "service method contract"
    if source == "model":
        return "model tool call"
    return "unknown source"
```

- [ ] **Step 7: Verify Task 6**

Run:

```bash
uv run pytest tests/test_agent_runner.py tests/test_cli_run.py -v
uv run ruff check agent/runner.py agent/tool_types.py cli/run.py tests/test_agent_runner.py tests/test_cli_run.py
uv run ty check agent/runner.py agent/tool_types.py cli/run.py tests/test_agent_runner.py tests/test_cli_run.py
```

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add agent/runner.py agent/tool_types.py cli/run.py tests/test_agent_runner.py tests/test_cli_run.py
git add -u agent/tool_policy.py tests/test_tool_policy.py
git commit -m "Record service method approval evidence"
```

---

### Task 7: Update Documentation And Supersede Hook Framing

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-06-28-pre-tool-use-approval-hook.md`

**Interfaces:**
- Documents method-level approval policy.
- Documents OR/AND approver joins and dependencies.
- Marks old hook plan as superseded.

- [ ] **Step 1: Update README key concepts**

Replace the current approval gate bullet with:

```markdown
- **Approval gate**: Service-enforced at the route/method level. Each side-effect method has an explicit approval policy that defines whether approval is required, whether approvers are `any` or `all`, and whether one approval depends on another. Service methods either execute, return `approval_required` with an `approval_request_id`, or reject the request. The runner only displays and records service results.
```

- [ ] **Step 2: Update README project structure**

Remove:

```markdown
│   ├── tool_policy.py  # Pre-tool-use approval and write-gate policy
```

Add under `core/`:

```markdown
│   ├── approval_policy.py # Route/method approval requirements and approver graphs
```

- [ ] **Step 3: Mark old plan superseded**

At the top of `docs/superpowers/plans/2026-06-28-pre-tool-use-approval-hook.md`, insert:

```markdown
> Superseded by `docs/superpowers/plans/2026-06-28-service-layer-approval-contract.md`. The repo is a service layer, so approvals are now route/method policy with OR/AND approver graphs and dependencies, not runner-owned pre-tool hooks.
```

- [ ] **Step 4: Verify docs**

Run:

```bash
rg -n "pre-tool-use|pre_tool_hook|tool_policy|before_tool_use|ToolUseRequest" README.md docs agent tests cli
```

Expected: matches may remain only in the superseded old plan and historical notes. There must be no runtime code or active tests importing `agent.tool_policy`, `before_tool_use`, or `ToolUseRequest`.

- [ ] **Step 5: Commit**

```bash
git add README.md docs/superpowers/plans/2026-06-28-pre-tool-use-approval-hook.md
git commit -m "Document method-level approval policy"
```

---

### Task 8: End-To-End Verification

**Files:**
- No new code unless previous gates fail.

**Interfaces:**
- Verifies method policy, grouped approvals, API route gates, client contract, runner evidence, CLI rendering, docs, lint, and scoped type checks.

- [ ] **Step 1: Run targeted suite**

Run:

```bash
uv run pytest \
  tests/test_governance.py \
  tests/test_database.py \
  tests/test_approval.py \
  tests/test_api.py \
  tests/test_revmem_client.py \
  tests/test_agent_runner.py \
  tests/test_cli_run.py \
  tests/test_agent_tools.py \
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
  core/approval_policy.py \
  core/models.py \
  core/database.py \
  api/approval_gate.py \
  api/routes.py \
  agent/revmem_client.py \
  agent/tools.py \
  agent/prompts.py \
  agent/templates/skill_md.py \
  agent/tool_types.py \
  agent/runner.py \
  cli/run.py \
  tests/test_governance.py \
  tests/test_database.py \
  tests/test_approval.py \
  tests/test_api.py \
  tests/test_revmem_client.py \
  tests/test_agent_runner.py \
  tests/test_cli_run.py \
  tests/test_agent_tools.py
```

Expected: all pass.

- [ ] **Step 5: Record full type-check status**

Run:

```bash
uv run ty check
```

Expected: may still fail on unrelated existing diagnostics in `agent/spike.py`, `evals/harness.py`, `tests/test_context.py`, and `tests/test_session.py`. Do not claim full project type-clean unless this command passes.

- [ ] **Step 6: Manual local API smoke**

Terminal 1:

```bash
REVMEM_DB=/private/tmp/revmem-method-approval-smoke.db \
REVMEM_BASE_URL=http://127.0.0.1:8010 \
uv run uvicorn api.main:app --host 127.0.0.1 --port 8010
```

Terminal 2:

```bash
uv run python -m cli.run --live --no-wait
```

Expected if Gemini calls a side-effect method: the CLI shows an approval from the service method contract, API logs show a route/method approval request, no side effect occurs before approval, and a later approved retry requires `approval_request_id`.

- [ ] **Step 7: Final repository review**

Run:

```bash
git status --short
git log --oneline -8
rg -n "before_tool_use|ToolUseRequest|pre_tool_hook|agent.tool_policy" agent api core cli tests README.md
```

Expected: working tree clean after commits. Runtime search results should be empty for removed hook symbols.

---

## Self-Review

**Spec coverage:** The plan now defines approvals at the route/method level, supports no-approval methods, OR approver groups, AND approver groups, approval dependencies, grouped approval persistence, multiple gated routes, and runner/client updates.

**Placeholder scan:** No placeholder markers, vague validation steps, or test-free implementation task remains. Each task includes exact files, concrete snippets, commands, and expected results.

**Type consistency:** `MethodApprovalPlan`, `ApprovalStep`, `approval_request_id`, and service method approval payloads are introduced before downstream API, client, and runner tasks consume them. `requires_approval` remains rejected as caller input.
