"""RevMem API client — wraps Person B's canonical REST contract.

Endpoints (no ``/api`` prefix — see the Person B plan / ARCHITECTURE.md):
    GET  /agents/{id}                      -> agent (+ allowed_tools)
    GET  /agents/{id}/skill.md             -> tier-scoped SKILL.md (text)
    POST /sessions                         -> session
    POST /sessions/{id}/complete           -> {session, agent}  (logs the outcome)
    GET  /memory/retrieve?agent_id=&query= -> list[memory]
    POST /memory                           -> memory
    GET  /contracts/{deal_id}              -> signed order form
    GET  /crm/{deal_id}                    -> CRM record
    POST /route_for_approval               -> {approval_id, route_to, status, ...}
    GET  /approvals/{id}/status            -> approval status (poll target)
    POST /crm/write                        -> {ok, decision, crm}  (or 403)

Calls use hardcoded stubs only when ``REVMEM_BASE_URL`` is unset or
``REVMEM_STUB_MODE=1``. With a base URL configured, transport failures raise
``RevMemApiError`` instead of silently falling back.
"""

import json
import os
from typing import Any
import urllib.error
import urllib.request
from urllib.parse import quote, urlencode

JsonObject = dict[str, Any]
JsonValue = JsonObject | list[Any]

REVMEM_BASE_URL = os.environ.get("REVMEM_BASE_URL", os.environ.get("REVMEM_API_URL", "")).rstrip("/")
STUB_MODE = os.environ.get("REVMEM_STUB_MODE") == "1" or not REVMEM_BASE_URL

_HEADERS = {"Content-Type": "application/json", "ngrok-skip-browser-warning": "1"}


class RevMemApiError(RuntimeError):
    """Raised when the live RevMem API cannot fulfill a request."""

    pass


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


def _expect_object(value: JsonValue, path: str) -> JsonObject:
    if isinstance(value, dict):
        return value
    raise RevMemApiError(f"{path} returned a list, expected object")


# --- Agent / session ----------------------------------------------------------

def get_agent(agent_id: str) -> JsonObject:
    path = f"/agents/{quote(agent_id)}"
    return _expect_object(_api_call("GET", path), path)


def ensure_agent(name: str) -> JsonObject:
    """Get-or-create the demo agent by name (idempotent). Returns the agent dict —
    the existing agent if one with this name exists, else a freshly created one.
    Lets each per-session run resolve the same agent and accumulate reputation."""
    return _expect_object(_api_call("POST", "/agents", {"name": name}), "/agents")


def get_skill_md(agent_id: str) -> str:
    """Tier-scoped SKILL.md (plain text). Empty string in stub mode."""
    if STUB_MODE:
        return ""
    url = f"{REVMEM_BASE_URL}/agents/{quote(agent_id)}/skill.md"
    req = urllib.request.Request(url, headers={"ngrok-skip-browser-warning": "1"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode()
    except urllib.error.HTTPError as e:
        raise RevMemApiError(f"GET /agents/{agent_id}/skill.md failed: {e.code} {e.reason}") from e
    except urllib.error.URLError as e:
        raise RevMemApiError(f"GET /agents/{agent_id}/skill.md failed: {e.reason}") from e


def start_session(agent_id: str, task: str, env_id: str | None = None) -> JsonObject:
    body: JsonObject = {"agent_id": agent_id, "task": task}
    if env_id:
        body["env_id"] = env_id
    return _expect_object(_api_call("POST", "/sessions", body), "/sessions")


def complete_session(session_id: str, outcome: JsonObject) -> JsonObject:
    """Close the session → RevMem updates reputation + memory relevance.

    ``outcome`` must include ``accuracy`` (float); may include ``memories_used`` /
    ``memories_created`` and any extra metrics (material_caught, false_escalations).
    Returns ``{"session": ..., "agent": ...}``."""
    path = f"/sessions/{quote(session_id)}/complete"
    return _expect_object(_api_call("POST", path, outcome), path)


# Back-compat alias for callers that say "log the outcome".
log_outcome = complete_session


# --- Memory -------------------------------------------------------------------

def retrieve_context(
    agent_id: str, query: str, memory_type: str | None = None, limit: int = 5
) -> JsonObject:
    """Reputation-reranked memories plus the active policy for this query."""
    params = {"agent_id": agent_id, "query": query, "limit": limit}
    if memory_type:
        params["type"] = memory_type
    result = _api_call("GET", f"/memory/retrieve?{urlencode(params)}")
    if isinstance(result, list):
        return {"memories": result, "policy": []}
    return result


def store_memory(
    session_id: str, agent_id: str, memory_type: str, content: str, metadata: JsonObject
) -> JsonObject:
    return _expect_object(
        _api_call(
            "POST",
            "/memory",
            {
                "session_id": session_id,
                "agent_id": agent_id,
                "type": memory_type,
                "content": content,
                "metadata": metadata,
            },
        ),
        "/memory",
    )


# --- Reconciliation tools -----------------------------------------------------

def get_contract(deal_id: str) -> JsonObject:
    path = f"/contracts/{quote(deal_id)}"
    return _expect_object(_api_call("GET", path), path)


def get_crm_record(deal_id: str) -> JsonObject:
    path = f"/crm/{quote(deal_id)}"
    return _expect_object(_api_call("GET", path), path)


def route_for_approval(
    deal_id: str, amount_usd: float, change_type: str, **extra: Any
) -> JsonObject:
    """Route a discrepancy for approval.

    The canonical API returns approval_id, route_to, and status. It does not
    return the human approval token or link to the agent.
    """
    body: JsonObject = {"deal_id": deal_id, "amount_usd": amount_usd, "change_type": change_type}
    body.update(extra)
    return _expect_object(_api_call("POST", "/route_for_approval", body), "/route_for_approval")


def get_approval_status(approval_id: str) -> JsonObject:
    """Poll target between route_for_approval and write_crm."""
    path = f"/approvals/{quote(approval_id)}/status"
    return _expect_object(_api_call("GET", path), path)


def write_crm(
    agent_id: str,
    deal_id: str,
    fields: JsonObject,
    discrepancy: JsonObject | None = None,
    approval_id: str | None = None,
) -> JsonObject:
    """Reconcile CRM to the signed contract. Server-gated by authorize_write —
    returns {ok, decision, crm} on ALLOW, otherwise an HTTP 403 (stubbed allow)."""
    return _expect_object(
        _api_call(
            "POST",
            "/crm/write",
            {
                "agent_id": agent_id,
                "deal_id": deal_id,
                "fields": fields,
                "discrepancy": discrepancy or {},
                "approval_id": approval_id,
            },
        ),
        "/crm/write",
    )


# --- Stub responses (no API yet) ----------------------------------------------

def _stub_agent(agent_id: str) -> JsonObject:
    return {
        "id": agent_id,
        "name": "RevOps Finance Agent",
        "reputation_score": 0.1,
        "total_sessions": 0,
        "successful_sessions": 0,
        "permission_tier": "observer",
        "allowed_tools": [
            "get_contract", "get_crm_record", "retrieve_context",
            "route_for_approval", "log_outcome",
        ],
    }


def _stub_response(method: str, path: str, body: JsonObject | None = None) -> JsonValue:
    """Hardcoded responses mirroring the canonical contract for offline dev."""
    if path == "/agents":  # register: get-or-create by name
        return _stub_agent("revops-agent-1")
    if path.startswith("/agents/") and path.endswith("/skill.md"):
        return {}
    if path.startswith("/agents/"):
        return _stub_agent(path.rsplit("/", 1)[-1])

    if path.startswith("/sessions/") and path.endswith("/complete"):
        print(f"[STUB] complete_session: {json.dumps(body)}")
        return {"session": {"id": path.split("/")[2], "status": "completed"},
                "agent": {"id": "revops-agent-1", "reputation_score": 0.2,
                          "permission_tier": "observer"}}
    if path == "/sessions":
        return {"id": "session-stub-001", "status": "running"}

    if path.startswith("/memory/retrieve"):
        return []  # cold start: no memories
    if path == "/memory":
        print(f"[STUB] store_memory: {(body or {}).get('content', '')[:80]}")
        return {"id": "mem-stub-001"}

    if path.startswith("/contracts/"):
        return {"deal_id": path.rsplit("/", 1)[-1]}
    if path.startswith("/crm/") and path != "/crm/write":
        return {"deal_id": path.rsplit("/", 1)[-1]}

    if path == "/route_for_approval":
        return {"approval_id": "appr-stub-001", "token": "stub-token",
                "route_to": (body or {}).get("change_type") == "discount_over_authority"
                and "cfo" or "controller",
                "status": "pending", "approval_link": "http://localhost:8000/approvals/appr-stub-001?token=stub-token"}
    if path.startswith("/approvals/") and path.endswith("/status"):
        return {"id": path.split("/")[2], "status": "approved"}  # stub auto-approves

    if path == "/crm/write":
        print(f"[STUB] write_crm: {json.dumps((body or {}).get('fields', {}))}")
        return {"ok": True, "decision": "allow", "crm": (body or {}).get("fields", {})}

    return {}
