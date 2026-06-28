from __future__ import annotations

import html
import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel

from core import context, database, governance, session
from core.models import Agent, Approval, ApprovalStatus, Memory, MemoryType
from data import seed

router = APIRouter()


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
    deal_id: str = ""
    amount_usd: float = 0.0
    change_type: str | None = None


class CrmWrite(BaseModel):
    agent_id: str
    deal_id: str
    fields: dict[str, Any]
    discrepancy: dict[str, Any] = {}
    approval_id: str | None = None


class PolicyEdit(BaseModel):
    condition: dict[str, Any] | None = None
    route_to: str | None = None


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
    approver = governance.route(body.model_dump(), database.list_policy(conn))
    approval = Approval(deal_id=body.deal_id, discrepancy=body.model_dump(),
                        approver_role=approver)
    database.insert_approval(conn, approval)
    base = os.getenv("REVMEM_BASE_URL", "")
    link = f"{base}/approvals/{approval.id}?token={approval.token}"
    print(f"[approval] route to {approver}: {link}")  # email is stubbed for the demo
    # Token intentionally NOT returned to the agent — the agent polls /approvals/{id}/status
    # (token-less); the human approver receives the link+token via the stubbed email (stdout).
    return {"approval_id": approval.id, "route_to": approver, "status": approval.status}


@router.post("/crm/write")
def write_crm(body: CrmWrite, request: Request) -> dict[str, Any]:
    conn = _conn(request)
    agent = database.get_agent(conn, body.agent_id)
    if not agent:
        raise HTTPException(404, "unknown agent")
    approval_status = None
    if body.approval_id:
        appr = database.get_approval(conn, body.approval_id)
        # Bind approval to this specific write: foreign/mismatched approvals must not authorize it.
        if appr and appr.deal_id == body.deal_id and appr.discrepancy == body.discrepancy:
            approval_status = appr.status
        else:
            approval_status = None
    decision = governance.authorize_write(agent.permission_tier, body.discrepancy,
                                          approval_status)
    if decision != governance.WriteDecision.ALLOW:
        raise HTTPException(403, f"write not allowed ({decision}) — route_for_approval first")
    record = database.get_crm(conn, body.deal_id) or {}
    record.update(body.fields)
    database.upsert_crm(conn, body.deal_id, record)
    return {"ok": True, "decision": decision, "crm": record}


_APPROVAL_HTML = """<!doctype html><html><head><title>RevMem Approval</title></head>
<body style="font-family:system-ui;max-width:34rem;margin:4rem auto">
<h2>Pricing reconciliation approval</h2>
<p><b>Deal:</b> {deal_id} &nbsp; <b>Routed to:</b> {approver_role}</p>
<pre>{discrepancy}</pre>
<p><b>Status:</b> {status}</p>
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
                   f'<button name="decision" value="approve">Approve</button> '
                   f'<button name="decision" value="reject">Reject</button></form>')
    else:
        actions = "<p><i>Decision recorded.</i></p>"
    return _APPROVAL_HTML.format(deal_id=html.escape(a.deal_id),
                                 approver_role=html.escape(a.approver_role),
                                 discrepancy=html.escape(json.dumps(a.discrepancy, indent=2)),
                                 status=html.escape(a.status), actions=actions)


@router.post("/approvals/{approval_id}/decision")
def approval_decision(approval_id: str, request: Request,
                      decision: str = Form(...), token: str = Form(...)) -> dict[str, Any]:
    conn = _conn(request)
    a = database.get_approval(conn, approval_id)
    if not a or a.token != token:
        raise HTTPException(404, "unknown approval")
    if a.status != ApprovalStatus.PENDING:
        return a.model_dump(mode="json")
    a.status = ApprovalStatus.APPROVED if decision == "approve" else ApprovalStatus.REJECTED
    a.decided_at = datetime.now(timezone.utc)
    database.update_approval(conn, a)
    return a.model_dump(mode="json")


@router.get("/approvals/{approval_id}/status")
def approval_status(approval_id: str, request: Request) -> dict[str, Any]:
    # JSON status — the AGENT polls this between route_for_approval and write_crm.
    # This endpoint is NOT token-gated, so it must NOT leak the approval token
    # (which would let an id-holder self-approve via the decision endpoint).
    a = database.get_approval(_conn(request), approval_id)
    if not a:
        raise HTTPException(404, "unknown approval")
    return a.model_dump(mode="json", exclude={"token"})


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
def edit_policy(policy_id: str, body: PolicyEdit, request: Request) -> dict[str, Any]:
    conn = _conn(request)
    r = database.get_policy(conn, policy_id)
    if not r:
        raise HTTPException(404, "unknown policy rule")
    if body.condition is not None:
        r.condition = body.condition
    if body.route_to is not None:
        r.route_to = body.route_to
    r.version += 1
    database.upsert_policy(conn, r)
    return r.model_dump(mode="json")
