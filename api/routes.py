from __future__ import annotations

import html
import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel

from api import approval_gate
from api.approval_gate import ensure_method_approved
from core import context, database, governance, session
from core import approval_policy
from core.models import Agent, Approval, ApprovalStatus, Memory, MemoryType, PermissionTier
from data import seed

router = APIRouter()

TRUSTED_REROUTE_ROLES = {"controller", "cfo", "finance_admin"}
REROUTE_TARGET_ROLES = {"am", "controller", "cfo", "cco", "finance_admin"}


def _conn(request: Request) -> sqlite3.Connection:
    return request.app.state.conn


class CreateAgent(BaseModel):
    name: str


class StartSession(BaseModel):
    agent_id: str
    task: str
    env_id: str | None = None


class Lesson(BaseModel):
    type: str = MemoryType.PRICING_FIELD_RULE
    content: str
    metadata: dict[str, Any] = {}


class CompleteSession(BaseModel):
    accuracy: float
    material_caught: int | None = None
    false_escalations: int | None = None
    routed_correctly: bool | None = None
    memories_used: list[str] = []
    memories_created: list[str] = []
    lesson: Lesson | None = None  # reviewer correction → seeded server-side, tier-gate bypassed


class CreateMemory(BaseModel):
    session_id: str
    agent_id: str
    type: str = MemoryType.PRICING_FIELD_RULE
    content: str
    metadata: dict[str, Any] = {}


class Discrepancy(BaseModel):
    agent_id: str
    deal_id: str = ""
    amount_usd: float = 0.0
    change_type: str | None = None
    summary: str = ""


class CrmWrite(BaseModel):
    agent_id: str
    deal_id: str
    fields: dict[str, Any]
    discrepancy: dict[str, Any] = {}
    approval_id: str | None = None
    approval_request_id: str | None = None


class PolicyEdit(BaseModel):
    condition: dict[str, Any] | None = None
    route_to: str | None = None
    approval_request_id: str | None = None


def _approval_rows(approvals: list[Approval]) -> list[dict[str, object]]:
    return [
        {
            "step_id": approval.step_id,
            "status": approval.status,
            "depends_on": approval.depends_on,
        }
        for approval in approvals
    ]


def _blocked_approval_response(
    gate: approval_gate.ApprovalGateResult,
    response: Response,
) -> dict[str, Any]:
    payload = gate.payload
    if payload.get("approval_required") and payload.get("approval_status") == ApprovalStatus.PENDING:
        response.status_code = status.HTTP_202_ACCEPTED
        return payload
    reason = str(payload.get("reason", "approval request is not satisfied"))
    raise HTTPException(status.HTTP_403_FORBIDDEN, reason)


def _role_label(role: str) -> str:
    labels = {"am": "AM", "cco": "CCO", "cfo": "CFO"}
    return labels.get(role, role.replace("_", " ").title())


def _approval_link(approval: Approval) -> str:
    base = os.getenv("REVMEM_BASE_URL", "")
    return f"{base}/approvals/{approval.id}?token={approval.token}"


def _reroute_target(comment: str, current_role: str) -> str | None:
    normalized_current = current_role.lower()
    for role in sorted(REROUTE_TARGET_ROLES, key=len, reverse=True):
        if role == normalized_current:
            continue
        pattern = rf"\b{re.escape(role.replace('_', ' '))}\b"
        if re.search(pattern, comment, flags=re.IGNORECASE):
            return role
    return None


@router.post("/agents")
def create_agent(body: CreateAgent, request: Request) -> dict[str, Any]:
    # Idempotent register: get-or-create by name so each per-session run resolves
    # the same agent and reputation accumulates across runs.
    conn = _conn(request)
    a = database.get_agent_by_name(conn, body.name)
    if a is None:
        a = Agent(name=body.name)
        database.insert_agent(conn, a)
    out = a.model_dump(mode="json")
    out["allowed_tools"] = sorted(governance.allowed_tools(a.permission_tier))
    return out


@router.get("/agents/{agent_id}")
def get_agent(agent_id: str, request: Request) -> dict[str, Any]:
    a = database.get_agent(_conn(request), agent_id)
    if not a:
        raise HTTPException(404, "unknown agent")
    out = a.model_dump(mode="json")
    out["allowed_tools"] = sorted(governance.allowed_tools(a.permission_tier))
    return out


@router.get("/agents/{agent_id}/skill.md", response_class=PlainTextResponse)
def skill_md(agent_id: str, request: Request) -> str:
    a = database.get_agent(_conn(request), agent_id)
    if not a:
        raise HTTPException(404, "unknown agent")
    return governance.generate_skill_md(a.permission_tier)


@router.post("/sessions")
def start_session(body: StartSession, request: Request) -> dict[str, Any]:
    s = session.start(_conn(request), body.agent_id, body.task, body.env_id)
    return s.model_dump(mode="json")


@router.post("/sessions/{session_id}/complete")
def complete_session(session_id: str, body: CompleteSession, request: Request) -> dict[str, Any]:
    conn = _conn(request)
    s = database.get_session(conn, session_id)
    if not s:
        raise HTTPException(404, "unknown session")
    created = list(body.memories_created)
    # Reviewer correction: the lesson born from this outcome is seeded server-side.
    # The reviewer/system acts here, NOT the agent — so it skips the store_memory gate.
    if body.lesson is not None:
        mem = Memory(session_id=session_id, agent_id=s.agent_id, type=body.lesson.type,
                     content=body.lesson.content, metadata=body.lesson.metadata,
                     embedding=context.embed_text(body.lesson.content))
        database.insert_memory(conn, mem)
        created.append(mem.id)
    session.set_memories(conn, session_id, body.memories_used, created)
    # Persist the full outcome (accuracy + material_caught/false_escalations/routed_correctly),
    # dropping only the non-metric carrier fields. exclude_none keeps the stored row clean.
    outcome = body.model_dump(exclude={"lesson", "memories_used", "memories_created"},
                              exclude_none=True)
    s2, a = session.complete(conn, session_id, outcome)
    return {"session": s2.model_dump(mode="json"), "agent": a.model_dump(mode="json")}


@router.get("/sessions")
def list_sessions(request: Request) -> list[dict[str, Any]]:
    return [s.model_dump(mode="json") for s in database.list_sessions(_conn(request))]


@router.post("/memory")
def create_memory(body: CreateMemory, request: Request) -> dict[str, Any]:
    # This endpoint IS the agent's `store_memory` tool — gate it ANALYST+ server-side
    # (defense-in-depth). The reviewer's S1 lesson does NOT come through here; it is
    # seeded by log_outcome's `lesson` (a system action) above.
    conn = _conn(request)
    agent = database.get_agent(conn, body.agent_id)
    if not agent:
        raise HTTPException(404, "unknown agent")
    if not governance.can_use(agent.permission_tier, "store_memory"):
        raise HTTPException(403, f"tier {agent.permission_tier} cannot store_memory — ANALYST+ only")
    m = Memory(session_id=body.session_id, agent_id=body.agent_id, type=body.type,
               content=body.content, metadata=body.metadata,
               embedding=context.embed_text(body.content))
    database.insert_memory(conn, m)
    return m.model_dump(mode="json")


@router.get("/memory/retrieve")
def retrieve_memory(agent_id: str, query: str, request: Request,
                    type: str | None = None, limit: int = 5) -> dict[str, Any]:
    # retrieve_context returns reputation-reranked memories AND the active policy, so the
    # agent has the materiality thresholds it needs to judge what is material.
    conn = _conn(request)
    out = context.retrieve(conn, agent_id, query, type, limit)
    return {"memories": [m.model_dump(mode="json") for m in out],
            "policy": [r.model_dump(mode="json") for r in database.list_policy(conn)]}


@router.post("/route_for_approval")
def route_for_approval(body: Discrepancy, request: Request) -> dict[str, Any]:
    conn = _conn(request)
    agent = database.get_agent(conn, body.agent_id)
    if not agent:
        raise HTTPException(404, "unknown agent")
    if not governance.can_use(agent.permission_tier, "route_for_approval"):
        raise HTTPException(403, f"tier {agent.permission_tier} cannot route_for_approval")
    discrepancy = body.model_dump(exclude={"agent_id", "summary"})
    policy_rules = database.list_policy(conn)
    approver = governance.route(discrepancy, policy_rules)
    gate = ensure_method_approved(
        conn,
        "crm.write",
        {
            "tier": PermissionTier.ANALYST,
            "deal_id": body.deal_id,
            "discrepancy": discrepancy,
        },
        policy_rules=policy_rules,
    )
    payload = dict(gate.payload)
    payload["route_to"] = approver
    payload["status"] = payload.get("approval_status", ApprovalStatus.PENDING)
    for approval_ref in payload.get("approvals", []):
        if not isinstance(approval_ref, dict):
            continue
        approval = database.get_approval(conn, str(approval_ref.get("approval_id", "")))
        if approval is None:
            continue
        print(f"[approval] route to {approval.approver_role}: {_approval_link(approval)}")  # email is stubbed for the demo
    # Token intentionally NOT returned to the agent — the agent polls /approval-requests/{id}/status
    # (token-less); the human approver receives the link+token via the stubbed email (stdout).
    return payload


@router.post("/crm/write")
def write_crm(body: CrmWrite, request: Request, response: Response) -> dict[str, Any]:
    conn = _conn(request)
    agent = database.get_agent(conn, body.agent_id)
    if not agent:
        raise HTTPException(404, "unknown agent")
    if not governance.can_use(agent.permission_tier, "write_crm"):
        raise HTTPException(403, f"tier {agent.permission_tier} cannot write_crm")

    approval_request_id = body.approval_request_id
    if approval_request_id is None and body.approval_id:
        approval = database.get_approval(conn, body.approval_id)
        approval_request_id = approval.request_id if approval else None

    gate = ensure_method_approved(
        conn,
        "crm.write",
        {
            "tier": agent.permission_tier,
            "deal_id": body.deal_id,
            "discrepancy": body.discrepancy,
        },
        approval_request_id,
    )
    if not gate.allowed:
        return _blocked_approval_response(gate, response)

    record = database.get_crm(conn, body.deal_id) or {}
    record.update(body.fields)
    database.upsert_crm(conn, body.deal_id, record)
    return {**gate.payload, "crm": record}


@router.get("/approval-inbox/{role}", response_class=HTMLResponse)
def approval_inbox(role: str, request: Request) -> str:
    role_key = role.lower()
    approvals = database.list_pending_approvals_for_role(_conn(request), role_key)
    title = f"{_role_label(role_key)} Approval Inbox"
    links = "\n".join(
        (
            "<li>"
            f'<a href="{html.escape(_approval_link(approval), quote=True)}">'
            f"{html.escape(approval.deal_id)} - {html.escape(approval.method)}"
            "</a>"
            "</li>"
        )
        for approval in approvals
    )
    if not links:
        links = "<li>No pending approvals.</li>"
    return (
        "<!doctype html><html><head>"
        f"<title>{html.escape(title)}</title>"
        "</head><body style=\"font-family:system-ui;max-width:42rem;margin:4rem auto\">"
        f"<h1>{html.escape(title)}</h1>"
        "<p>Unauthenticated local demo inbox.</p>"
        f"<ul>{links}</ul>"
        "</body></html>"
    )


_APPROVAL_HTML = """<!doctype html><html><head><title>RevMem Approval</title></head>
<body style="font-family:system-ui;max-width:34rem;margin:4rem auto">
<h2>Pricing reconciliation approval</h2>
<p><b>Deal:</b> {deal_id} &nbsp; <b>Routed to:</b> {approver_role}</p>
<pre>{discrepancy}</pre>
<p><b>Status:</b> {status}</p>
<p><b>Comment:</b> {comment}</p>
{actions}
</body></html>"""


@router.get("/approvals/{approval_id}", response_class=HTMLResponse)
def approval_page(approval_id: str, token: str, request: Request) -> str:
    a = database.get_approval(_conn(request), approval_id)
    if not a or a.token != token:
        raise HTTPException(404, "unknown approval")
    if a.status == ApprovalStatus.PENDING:
        safe_id = html.escape(a.id)
        safe_token = html.escape(a.token)
        actions = (f'<form method="post" action="/approvals/{safe_id}/decision">'
                    f'<input type="hidden" name="token" value="{safe_token}">'
                   '<p><label>Comment<br><textarea name="comment" rows="4" '
                   'style="width:100%"></textarea></label></p>'
                    f'<button name="decision" value="approve">Approve</button> '
                   f'<button name="decision" value="deny">Deny</button></form>')
    else:
        actions = "<p><i>Decision recorded.</i></p>"
    return _APPROVAL_HTML.format(deal_id=html.escape(a.deal_id),
                                 approver_role=html.escape(a.approver_role),
                                 discrepancy=html.escape(json.dumps(a.discrepancy, indent=2)),
                                 status=html.escape(a.status),
                                 comment=html.escape(a.comment),
                                 actions=actions)


def _seed_approval_lesson(conn: sqlite3.Connection, a: Approval, decision: str) -> None:
    """Turn an approver's comment into a shared lesson — org-wide context surfaced to
    every agent via retrieve_context, not memory tied to one agent."""
    change_type = a.discrepancy.get("change_type", "") if isinstance(a.discrepancy, dict) else ""
    verb = "approved" if decision == "approve" else "rejected"
    lesson = (
        f"Approver feedback on {a.deal_id} ({change_type or 'discrepancy'}) — "
        f"{verb} by {a.approver_role}: {a.comment}"
    )
    database.insert_memory(conn, Memory(
        session_id=f"approval:{a.request_id}",
        agent_id=context.SHARED_MEMORY_AGENT_ID,
        type="approval_feedback",
        content=lesson,
        metadata={
            "source": "approval", "approval_id": a.id, "deal_id": a.deal_id,
            "decision": decision, "approver_role": a.approver_role,
        },
        embedding=context.embed_text(lesson),
    ))


@router.post("/approvals/{approval_id}/decision")
def approval_decision(approval_id: str, request: Request,
                      decision: str = Form(...), token: str = Form(...),
                      comment: str = Form("")) -> dict[str, Any]:
    conn = _conn(request)
    a = database.get_approval(conn, approval_id)
    if not a or a.token != token:
        raise HTTPException(404, "unknown approval")
    if a.status != ApprovalStatus.PENDING:
        return a.model_dump(mode="json")
    normalized_decision = "reject" if decision == "deny" else decision
    if normalized_decision not in {"approve", "reject"}:
        raise HTTPException(400, "decision must be approve or deny")
    a.comment = comment.strip()
    if normalized_decision == "approve":
        approvals = database.list_approvals_for_request(conn, a.request_id)
        if not approval_policy.dependencies_satisfied(a.step_id, _approval_rows(approvals)):
            raise HTTPException(409, f"approval {a.step_id} has unsatisfied dependencies")
        a.status = ApprovalStatus.APPROVED
    else:
        target_role = None
        if a.approver_role in TRUSTED_REROUTE_ROLES:
            target_role = _reroute_target(a.comment, a.approver_role)
        if target_role:
            siblings = database.list_approvals_for_request(conn, a.request_id)
            if not any(approval.approver_role == target_role for approval in siblings):
                database.insert_approval(
                    conn,
                    Approval(
                        request_id=a.request_id,
                        method=a.method,
                        join=a.join,
                        step_id=target_role,
                        deal_id=a.deal_id,
                        discrepancy=a.discrepancy,
                        approver_role=target_role,
                    ),
                )
            a.status = ApprovalStatus.REROUTED
        else:
            a.status = ApprovalStatus.REJECTED
    a.decided_at = datetime.now(timezone.utc)
    database.update_approval(conn, a)
    if a.comment:
        _seed_approval_lesson(conn, a, normalized_decision)
    return a.model_dump(mode="json")


@router.get("/approvals/{approval_id}/status")
def approval_status(approval_id: str, request: Request) -> dict[str, Any]:
    # JSON status for one human approval task.
    # This endpoint is NOT token-gated, so it must NOT leak the approval token
    # (which would let an id-holder self-approve via the decision endpoint).
    a = database.get_approval(_conn(request), approval_id)
    if not a:
        raise HTTPException(404, "unknown approval")
    return a.model_dump(mode="json", exclude={"token"})


@router.get("/approval-requests")
def list_approval_requests(request: Request, deal_id: str | None = None) -> list[dict[str, Any]]:
    """List approval requests (one per request_id), optionally filtered by deal. Used to
    reconstruct governed-action evidence when tools run server-side over MCP."""
    out: list[dict[str, Any]] = []
    for a in database.list_approval_requests(_conn(request), deal_id):
        out.append({
            "request_id": a.request_id,
            "deal_id": a.deal_id,
            "change_type": a.discrepancy.get("change_type", ""),
            "amount_usd": a.discrepancy.get("amount_usd"),
            "route_to": a.approver_role,
            "status": a.status,
        })
    return out


@router.get("/approval-requests/{request_id}/status")
def approval_request_status(request_id: str, request: Request) -> dict[str, Any]:
    approvals = database.list_approvals_for_request(_conn(request), request_id)
    if not approvals:
        raise HTTPException(404, "unknown approval request")
    payload = approval_gate.approval_request_payload(approvals, "")
    payload["status"] = payload["approval_status"]
    return payload


@router.get("/contracts/{deal_id}")
def get_contract(deal_id: str) -> dict[str, Any]:
    c = seed.load_contract(deal_id)
    if not c:
        raise HTTPException(404, "unknown deal")
    return c


@router.get("/crm/{deal_id}")
def get_crm_record(deal_id: str, request: Request) -> dict[str, Any]:
    r = database.get_crm(_conn(request), deal_id)
    if not r:
        raise HTTPException(404, "unknown deal")
    return r


@router.get("/policy")
def get_policy(request: Request) -> list[dict[str, Any]]:
    return [r.model_dump(mode="json") for r in database.list_policy(_conn(request))]


@router.put("/policy/{policy_id}")
def edit_policy(policy_id: str, body: PolicyEdit, request: Request, response: Response) -> dict[str, Any]:
    conn = _conn(request)
    r = database.get_policy(conn, policy_id)
    if not r:
        raise HTTPException(404, "unknown policy rule")
    requested_change: dict[str, Any] = {
        "policy_id": policy_id,
        "condition": body.condition,
        "route_to": body.route_to,
    }
    gate = ensure_method_approved(
        conn,
        "policy.update",
        {"tier": PermissionTier.ANALYST, "discrepancy": requested_change},
        body.approval_request_id,
    )
    if not gate.allowed:
        return _blocked_approval_response(gate, response)
    if body.condition is not None:
        r.condition = body.condition
    if body.route_to is not None:
        r.route_to = body.route_to
    r.version += 1
    database.upsert_policy(conn, r)
    return r.model_dump(mode="json")
