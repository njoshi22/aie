"""Approval state + the ``/approve/{token}`` endpoint (FastAPI).

Flow:
    CLI: create_approval(...) -> email CFO a magic link -> wait_for_approval(token)
    CFO: clicks link -> GET /approve/{token} flips state to approved
    CLI: poll returns -> agent resumes -> executes the CRM write

Approval-state contract (coordinate with Person B's Atlas ``approvals`` collection):
    token, deal_id, approver, approver_email, discrepancy, recommended_fix,
    amount_usd, status (pending|approved|rejected), created_at, decided_at

Scaffold backend = a JSON file so the CLI process and the FastAPI process share
state without Atlas. Swap ``ApprovalStore`` for an Atlas-backed store at
integration (see TODO below).

Run the endpoint standalone:
    uv run uvicorn notify.approve:app --port 8000
Or mount into Person B's API:
    from notify.approve import router; app.include_router(router)
"""

from __future__ import annotations

import json
import os
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

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

Status = Literal["pending", "approved", "rejected"]

STORE_PATH = Path(os.environ.get("REVMEM_APPROVALS_PATH", ".revmem_approvals.json"))
APPROVAL_BASE_URL = os.environ.get("APPROVAL_BASE_URL", "http://localhost:8000")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ApprovalRequest(BaseModel):
    token: str
    deal_id: str
    approver: str = "cfo"
    approver_email: str
    discrepancy: str
    recommended_fix: str
    amount_usd: Optional[float] = None
    status: Status = "pending"
    created_at: str = Field(default_factory=_now)
    decided_at: Optional[str] = None

    def approve_url(self) -> str:
        return f"{APPROVAL_BASE_URL}/approve/{self.token}"


class ApprovalStore:
    """File-backed approval store (scaffold).

    TODO(integration): replace with an Atlas-backed store via core/atlas.py so
    the approval contract lives in the shared ``approvals`` collection.
    """

    def __init__(self, path: Path = STORE_PATH):
        self.path = path

    @contextmanager
    def _locked(self):
        """Cross-process exclusive lock around read-modify-write (POSIX).

        Prevents concurrent writers from clobbering each other once the router
        runs behind a real server. No-op where fcntl is unavailable."""
        if fcntl is None:
            yield
            return
        lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        with open(lock_path, "w") as fh:
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
        self.path.write_text(json.dumps(data, indent=2))

    def put(self, approval: ApprovalRequest) -> ApprovalRequest:
        with self._locked():
            data = self._load()
            data[approval.token] = approval.model_dump()
            self._save(data)
        return approval

    def get(self, token: str) -> ApprovalRequest | None:
        raw = self._load().get(token)
        return ApprovalRequest(**raw) if raw else None

    def set_status(self, token: str, status: Status) -> ApprovalRequest:
        with self._locked():
            data = self._load()
            if token not in data:
                raise KeyError(token)
            data[token]["status"] = status
            data[token]["decided_at"] = _now()
            self._save(data)
        return ApprovalRequest(**data[token])


store = ApprovalStore()


def create_approval(
    deal_id: str,
    approver_email: str,
    discrepancy: str,
    recommended_fix: str,
    amount_usd: float | None = None,
    approver: str = "cfo",
) -> ApprovalRequest:
    """Create and persist a pending approval. Returns it (token + approve_url)."""
    approval = ApprovalRequest(
        token=uuid.uuid4().hex,
        deal_id=deal_id,
        approver=approver,
        approver_email=approver_email,
        discrepancy=discrepancy,
        recommended_fix=recommended_fix,
        amount_usd=amount_usd,
    )
    return store.put(approval)


def wait_for_approval(
    token: str,
    timeout: float = 300.0,
    interval: float = 2.0,
    on_tick: Callable[[float], None] | None = None,
) -> ApprovalRequest:
    """Block until the approval is approved/rejected, or raise TimeoutError."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        approval = store.get(token)
        if approval and approval.status != "pending":
            return approval
        if on_tick:
            on_tick(deadline - time.monotonic())
        time.sleep(interval)
    raise TimeoutError(f"approval {token} not decided within {timeout:.0f}s")


# --- HTTP layer ---------------------------------------------------------------

router = APIRouter(tags=["approval"])


def _confirmation_page(title: str, message: str, accent: str) -> str:
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>RevMem - {title}</title></head>
<body style="margin:0;font-family:Inter,Arial,sans-serif;background:#F5F3EE;color:#1B2A16">
  <div style="max-width:480px;margin:18vh auto;background:#fff;border-radius:14px;padding:40px;text-align:center">
    <div style="font-size:40px;color:{accent}">&#10003;</div>
    <h1 style="font-family:Georgia,serif;font-size:26px;margin:12px 0 8px">{title}</h1>
    <p style="color:#555;margin:0">{message}</p>
    <p style="color:#aaa;font-size:12px;margin-top:28px">RevMem - governed agent memory</p>
  </div>
</body></html>"""


def _page_for(approval: ApprovalRequest) -> str:
    """Render the confirmation page for the approval's ACTUAL status, so a late
    or conflicting click (e.g. reject after approve) never shows a false result."""
    if approval.status == "approved":
        return _confirmation_page(
            "Approved",
            f"Correction for {approval.deal_id} is approved. The agent will execute the CRM write.",
            "#4E6639",
        )
    if approval.status == "rejected":
        return _confirmation_page(
            "Rejected",
            f"Correction for {approval.deal_id} was rejected. The agent will leave the CRM unchanged.",
            "#9A3B2E",
        )
    return _confirmation_page(
        "Pending",
        f"Correction for {approval.deal_id} is still awaiting a decision.",
        "#7A6A4F",
    )


@router.get("/approve/{token}", response_class=HTMLResponse)
def approve(token: str) -> HTMLResponse:
    approval = store.get(token)
    if not approval:
        raise HTTPException(status_code=404, detail="unknown approval token")
    if approval.status == "pending":
        approval = store.set_status(token, "approved")
    return HTMLResponse(_page_for(approval))


@router.get("/reject/{token}", response_class=HTMLResponse)
def reject(token: str) -> HTMLResponse:
    approval = store.get(token)
    if not approval:
        raise HTTPException(status_code=404, detail="unknown approval token")
    if approval.status == "pending":
        approval = store.set_status(token, "rejected")
    return HTMLResponse(_page_for(approval))


@router.get("/approval/{token}")
def approval_status(token: str) -> dict:
    """JSON status, used by the CLI poller and by Person B's API."""
    approval = store.get(token)
    if not approval:
        raise HTTPException(status_code=404, detail="unknown approval token")
    return approval.model_dump()


@router.get("/health")
def health() -> dict:
    return {"ok": True, "store": str(STORE_PATH)}


# Standalone app for local dev; Person B can include_router(router) instead.
app = FastAPI(title="RevMem approval service")
app.include_router(router)
