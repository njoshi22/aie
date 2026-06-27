"""
RevMem API client — stubs all endpoints with hardcoded responses
until Person B's API is live. Swap REVMEM_API_URL to real endpoint when ready.
"""
import os
import json
import urllib.request
import urllib.error

REVMEM_API_URL = os.environ.get("REVMEM_API_URL", "")
STUB_MODE = not REVMEM_API_URL


def _api_call(method: str, path: str, body: dict | None = None) -> dict:
    if STUB_MODE:
        return _stub_response(path, body)

    url = f"{REVMEM_API_URL}{path}"
    data = json.dumps(body).encode() if body else None
    headers = {"Content-Type": "application/json"}
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.URLError as e:
        print(f"[RevMem API error] {method} {path}: {e}")
        return _stub_response(path, body)


def get_agent(agent_id: str) -> dict:
    return _api_call("GET", f"/api/agent/{agent_id}")


def retrieve_context(deal_type: str, query: str) -> list[dict]:
    result = _api_call("GET", f"/api/memory/retrieve?type={deal_type}&query={query}")
    return result.get("memories", [])


def log_outcome(session_id: str, outcome: dict) -> dict:
    return _api_call("POST", "/api/feedback", {
        "session_id": session_id,
        "outcome": outcome,
    })


def store_memory(session_id: str, agent_id: str, memory_type: str, content: str, metadata: dict) -> dict:
    return _api_call("POST", "/api/memory", {
        "session_id": session_id,
        "agent_id": agent_id,
        "type": memory_type,
        "content": content,
        "metadata": metadata,
    })


def start_session(agent_id: str, task: str) -> dict:
    return _api_call("POST", "/api/session", {
        "agent_id": agent_id,
        "task": task,
    })


def _stub_response(path: str, body: dict | None = None) -> dict:
    """Hardcoded responses for development without Person B's API."""
    if "/api/agent/" in path:
        return {
            "id": "revops-agent-1",
            "name": "RevOps Finance Agent",
            "reputation_score": 0.1,
            "total_sessions": 0,
            "successful_sessions": 0,
            "permission_tier": "observer",
        }

    if "/api/memory/retrieve" in path:
        return {"memories": []}

    if "/api/feedback" in path:
        print(f"[STUB] Logged outcome: {json.dumps(body, indent=2)}")
        return {"status": "ok"}

    if "/api/memory" in path:
        print(f"[STUB] Stored memory: {body.get('content', '')[:80]}...")
        return {"id": "mem-stub-001", "status": "ok"}

    if "/api/session" in path:
        return {"id": "session-stub-001", "status": "running"}

    return {}
