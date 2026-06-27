"""Approval state + the CFO approval endpoints (FastAPI).

This is the **scaffold stand-in for Person B's approval surface**. It exposes the
exact contract Person B's RevMem API will serve, so the CLI does not change at
integration — point ``REVMEM_BASE_URL`` at Person B's API and these endpoints
simply drop out.

Canonical contract (Person B design — see the Person B plan, Task 8.5):
    POST /route_for_approval         -> create a pending approval, return the link
    GET  /approvals/{id}?token=...   -> render the confirm page (NO state change)
    POST /approvals/{id}/decision    -> approve/reject (state change; form POST)
    GET  /approvals/{id}/status      -> JSON status (CLI / agent poller)

Security: the GET never mutates. Email gateways, link scanners, and preview bots
routinely prefetch GET URLs — a GET that approved would let the gate auto-fire
before the CFO clicks. State only changes on the POST from the confirm button.

Approval record (maps onto Person B's SQLite ``approvals`` table):
    id, token, deal_id, approver_role, approver_email, discrepancy,
    recommended_fix, amount_usd, change_type, status, created_at, decided_at
``approver_email`` / ``recommended_fix`` / ``amount_usd`` / ``change_type`` fold
into Person B's ``discrepancy`` dict + role->email policy resolution at integration.

Backend = a 0600 JSON file so the CLI process and the endpoint process share state
without a DB. Person B swaps ``ApprovalStore`` for the SQLite ``approvals`` table.

Run the endpoint standalone:
    uv run uvicorn notify.approve:app --port 8000
Or mount into Person B's API:
    from notify.approve import router; app.include_router(router)
"""

from __future__ import annotations

import html
import json
import os
import tempfile
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal, Optional

try:
    import fcntl  # POSIX advisory file lock (mac/linux)
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None

from fastapi import APIRouter, FastAPI, Form, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

Status = Literal["pending", "approved", "rejected"]

STORE_PATH = Path(os.environ.get("REVMEM_APPROVALS_PATH", ".revmem_approvals.json"))
# Aligned with the CLI/agent: REVMEM_BASE_URL is the canonical var; fall back to
# the legacy APPROVAL_BASE_URL, then localhost.
APPROVAL_BASE_URL = os.environ.get(
    "REVMEM_BASE_URL", os.environ.get("APPROVAL_BASE_URL", "http://localhost:8000")
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _id() -> str:
    return uuid.uuid4().hex


class ApprovalRequest(BaseModel):
    id: str = Field(default_factory=_id)          # path id (referenced + polled)
    token: str = Field(default_factory=_id)        # secret that guards the decision
    deal_id: str
    approver_role: str = "cfo"                     # am | controller | cfo | cco
    approver_email: str
    discrepancy: str
    recommended_fix: str
    amount_usd: Optional[float] = None
    change_type: str = "schedule_change"           # feeds Person B's authorize_write
    status: Status = "pending"
    created_at: str = Field(default_factory=_now)
    decided_at: Optional[str] = None

    def approve_url(self) -> str:
        return f"{APPROVAL_BASE_URL}/approvals/{self.id}?token={self.token}"

    def status_url(self) -> str:
        return f"{APPROVAL_BASE_URL}/approvals/{self.id}/status"


class ApprovalStore:
    """File-backed approval store (scaffold).

    Stand-in for Person B's SQLite ``approvals`` table; the HTTP contract above is
    what survives integration, not this backend.
    """

    def __init__(self, path: Path = STORE_PATH):
        self.path = path

    @contextmanager
    def _locked(self):
        """Cross-process exclusive lock around read-modify-write (POSIX).

        Prevents concurrent writers from clobbering each other once the router runs
        behind a real server. No-op where fcntl is unavailable."""
        if fcntl is None:
            yield
            return
        lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        fd = os.open(str(lock_path), os.O_CREAT | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)

    def _load(self) -> dict[str, dict]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text())
        except json.JSONDecodeError:
            return {}

    def _save(self, data: dict[str, dict]) -> None:
        """Atomic, owner-only (0600) write so approval metadata isn't world-readable."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=".approvals.")
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w") as fh:
                json.dump(data, fh, indent=2)
            os.replace(tmp, self.path)
        except BaseException:
            os.unlink(tmp)
            raise

    def put(self, approval: ApprovalRequest) -> ApprovalRequest:
        with self._locked():
            data = self._load()
            data[approval.id] = approval.model_dump()
            self._save(data)
        return approval

    def get(self, approval_id: str) -> ApprovalRequest | None:
        raw = self._load().get(approval_id)
        return ApprovalRequest(**raw) if raw else None

    def set_status(self, approval_id: str, status: Status) -> ApprovalRequest:
        with self._locked():
            data = self._load()
            if approval_id not in data:
                raise KeyError(approval_id)
            data[approval_id]["status"] = status
            data[approval_id]["decided_at"] = _now()
            self._save(data)
        return ApprovalRequest(**data[approval_id])


store = ApprovalStore()


def create_approval(
    deal_id: str,
    approver_email: str,
    discrepancy: str,
    recommended_fix: str,
    amount_usd: float | None = None,
    approver_role: str = "cfo",
    change_type: str = "schedule_change",
) -> ApprovalRequest:
    """Create and persist a pending approval. Returns it (id, token, approve_url)."""
    approval = ApprovalRequest(
        deal_id=deal_id,
        approver_role=approver_role,
        approver_email=approver_email,
        discrepancy=discrepancy,
        recommended_fix=recommended_fix,
        amount_usd=amount_usd,
        change_type=change_type,
    )
    return store.put(approval)


def wait_for_approval(
    approval_id: str,
    timeout: float = 300.0,
    interval: float = 2.0,
    on_tick: Callable[[float], None] | None = None,
) -> ApprovalRequest:
    """Block until the approval is approved/rejected, or raise TimeoutError."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        approval = store.get(approval_id)
        if approval and approval.status != "pending":
            return approval
        if on_tick:
            on_tick(deadline - time.monotonic())
        time.sleep(interval)
    raise TimeoutError(f"approval {approval_id} not decided within {timeout:.0f}s")


# --- HTTP layer ---------------------------------------------------------------

router = APIRouter(tags=["approval"])


class RouteRequest(BaseModel):
    """Body for POST /route_for_approval (callable by the agent or Person B)."""

    deal_id: str
    approver_email: str
    discrepancy: str
    recommended_fix: str
    amount_usd: Optional[float] = None
    approver_role: str = "cfo"
    change_type: str = "schedule_change"


def _shell(title: str, accent: str, inner: str) -> str:
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>RevMem - {title}</title></head>
<body style="margin:0;font-family:Inter,Arial,sans-serif;background:#F5F3EE;color:#1B2A16">
  <div style="max-width:480px;margin:18vh auto;background:#fff;border-radius:14px;padding:40px;text-align:center">
    <div style="font-size:40px;color:{accent}">&#10003;</div>
    <h1 style="font-family:Georgia,serif;font-size:26px;margin:12px 0 8px">{title}</h1>
    {inner}
    <p style="color:#aaa;font-size:12px;margin-top:28px">RevMem - governed agent memory</p>
  </div>
</body></html>"""


def _confirm_form_page(a: ApprovalRequest) -> str:
    """Pending GET: render the decision form. The buttons POST — GET never mutates.

    Every interpolated field is HTML-escaped: discrepancy/recommended_fix derive
    from contract data and must never be trusted as markup."""
    deal = html.escape(a.deal_id)
    role = html.escape(a.approver_role).upper()
    disc = html.escape(a.discrepancy)
    fix = html.escape(a.recommended_fix)
    aid = html.escape(a.id, quote=True)
    tok = html.escape(a.token, quote=True)
    inner = f"""
    <p style="color:#555;margin:0 0 6px">Deal <b>{deal}</b> needs {role} sign-off.</p>
    <p style="color:#555;margin:0 0 4px">{disc}</p>
    <p style="color:#777;font-size:13px;margin:0 0 24px">Recommended: {fix}</p>
    <form method="post" action="/approvals/{aid}/decision" style="display:flex;gap:12px;justify-content:center">
      <input type="hidden" name="token" value="{tok}">
      <button name="decision" value="approve" style="background:#4E6639;color:#fff;border:0;border-radius:8px;padding:12px 26px;font-weight:600;cursor:pointer">Approve correction</button>
      <button name="decision" value="reject" style="background:#fff;color:#9A3B2E;border:1px solid #9A3B2E;border-radius:8px;padding:12px 26px;font-weight:600;cursor:pointer">Reject</button>
    </form>"""
    return _shell("Confirm approval", "#7A6A4F", inner)


def _result_page(a: ApprovalRequest) -> str:
    """Render the result for the approval's ACTUAL status, so a late or conflicting
    click (e.g. reject after approve) never shows a false result."""
    deal = html.escape(a.deal_id)
    if a.status == "approved":
        msg, accent = f"Correction for {deal} is approved. The agent will execute the CRM write.", "#4E6639"
    elif a.status == "rejected":
        msg, accent = f"Correction for {deal} was rejected. The agent will leave the CRM unchanged.", "#9A3B2E"
    else:
        return _confirm_form_page(a)
    return _shell(a.status.capitalize(), accent, f'<p style="color:#555;margin:0">{msg}</p>')


@router.post("/route_for_approval")
def route_for_approval(req: RouteRequest) -> dict:
    approval = create_approval(
        deal_id=req.deal_id,
        approver_email=req.approver_email,
        discrepancy=req.discrepancy,
        recommended_fix=req.recommended_fix,
        amount_usd=req.amount_usd,
        approver_role=req.approver_role,
        change_type=req.change_type,
    )
    return {
        "approval_id": approval.id,
        "token": approval.token,
        "route_to": approval.approver_role,
        "status": approval.status,
        "approval_link": approval.approve_url(),
    }


@router.get("/approvals/{approval_id}", response_class=HTMLResponse)
def approval_page(approval_id: str, token: str) -> HTMLResponse:
    approval = store.get(approval_id)
    if not approval or approval.token != token:
        raise HTTPException(status_code=404, detail="unknown approval")
    return HTMLResponse(_result_page(approval))  # pending -> confirm form; else result


@router.post("/approvals/{approval_id}/decision", response_class=HTMLResponse)
def approval_decision(
    approval_id: str, decision: str = Form(...), token: str = Form(...)
) -> HTMLResponse:
    approval = store.get(approval_id)
    if not approval or approval.token != token:
        raise HTTPException(status_code=404, detail="unknown approval")
    if approval.status == "pending":
        new_status: Status = "approved" if decision == "approve" else "rejected"
        approval = store.set_status(approval_id, new_status)
    return HTMLResponse(_result_page(approval))


@router.get("/approvals/{approval_id}/status")
def approval_status(approval_id: str) -> dict:
    """JSON status, polled by the CLI and by the agent between route + write_crm."""
    approval = store.get(approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="unknown approval")
    return approval.model_dump()


@router.get("/health")
def health() -> dict:
    return {"ok": True, "store": str(STORE_PATH)}


# Standalone app for local dev; Person B can include_router(router) instead.
app = FastAPI(title="RevMem approval service")
app.include_router(router)
