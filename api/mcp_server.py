from __future__ import annotations

import sqlite3
from collections.abc import Callable, Sequence
from typing import Annotated, Any, Literal

from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_headers
from fastmcp.server.middleware import Middleware, MiddlewareContext
from fastmcp.server.middleware.middleware import CallNext, Tool
import mcp.types as mt
from pydantic import BaseModel, Field

from api import approval_gate
from api.approval_gate import ensure_method_approved
from core import context, database, governance
from core.models import Agent, ApprovalStatus, Memory, MemoryType, PermissionTier
from data import seed

JsonObject = dict[str, Any]
ConnectionProvider = Callable[[], sqlite3.Connection]
StringProvider = Callable[[], str | None]
ChangeType = Literal["schedule_change", "term_change", "rounding", "discount_over_authority"]
MemoryTypeName = Literal["lesson", "pattern", "warning", "pricing_field_rule"]

AGENT_ID_HEADER = "x-revmem-agent-id"
SESSION_ID_HEADER = "x-revmem-session-id"


class WriteDiscrepancy(BaseModel):
    deal_id: str = Field(description="Deal identifier for the discrepancy; should match the top-level deal_id.")
    amount_usd: float = Field(description="Absolute dollar impact of the discrepancy. Use 0 for non-dollar exceptions.")
    change_type: ChangeType = Field(description="Policy category for routing or approving the correction.")
    summary: str = Field(description="Brief explanation of what differs and why the correction is needed.")


def _header_value(name: str) -> str | None:
    headers = get_http_headers() or {}
    value = headers.get(name) or headers.get(name.lower()) or headers.get(name.upper())
    return str(value) if value else None


def _provided_or_header(provider: StringProvider | None, header: str) -> str | None:
    if provider is not None:
        return provider()
    return _header_value(header)


def _deny(reason: str) -> JsonObject:
    return {"ok": False, "decision": "deny", "approval_required": False, "reason": reason}


def _require_agent_tool(
    conn: sqlite3.Connection,
    agent_id_provider: StringProvider | None,
    tool_name: str,
) -> tuple[Agent | None, JsonObject | None]:
    agent_id = _provided_or_header(agent_id_provider, AGENT_ID_HEADER)
    if not agent_id:
        return None, _deny(f"missing {AGENT_ID_HEADER}")
    agent = database.get_agent(conn, agent_id)
    if agent is None:
        return None, _deny("unknown agent")
    if not governance.can_use(agent.permission_tier, tool_name):
        return None, _deny(f"tier {agent.permission_tier} cannot {tool_name}")
    return agent, None


def _allowed_tool_names(conn: sqlite3.Connection, agent_id_provider: StringProvider | None) -> set[str]:
    agent_id = _provided_or_header(agent_id_provider, AGENT_ID_HEADER)
    if not agent_id:
        return set()
    agent = database.get_agent(conn, agent_id)
    if agent is None:
        return set()
    return governance.allowed_tools(agent.permission_tier)


class ReputationToolFilter(Middleware):
    def __init__(self, conn_provider: ConnectionProvider, agent_id_provider: StringProvider | None) -> None:
        self._conn_provider = conn_provider
        self._agent_id_provider = agent_id_provider

    async def on_list_tools(
        self,
        context: MiddlewareContext[mt.ListToolsRequest],
        call_next: CallNext[mt.ListToolsRequest, Sequence[Tool]],
    ) -> Sequence[Tool]:
        tools = await call_next(context)
        allowed = _allowed_tool_names(self._conn_provider(), self._agent_id_provider)
        return [tool for tool in tools if tool.name in allowed]


def _approval_status_payload(conn: sqlite3.Connection, request_id: str) -> JsonObject:
    approvals = database.list_approvals_for_request(conn, request_id)
    if not approvals:
        return {"ok": False, "decision": "deny", "reason": "approval request not found"}
    payload = approval_gate.approval_request_payload(approvals, "")
    payload["status"] = payload["approval_status"]
    return payload


def create_revmem_mcp(
    conn_provider: ConnectionProvider,
    *,
    agent_id_provider: StringProvider | None = None,
    session_id_provider: StringProvider | None = None,
) -> FastMCP:
    mcp = FastMCP("RevMem")
    mcp.add_middleware(ReputationToolFilter(conn_provider, agent_id_provider))

    @mcp.tool
    def get_contract(
        deal_id: Annotated[str, Field(description="Canonical deal identifier, such as acme or globex.")],
    ) -> JsonObject:
        """Fetch the signed contract/order form. Returns source-of-truth contract pricing fields."""
        conn = conn_provider()
        _, error = _require_agent_tool(conn, agent_id_provider, "get_contract")
        if error:
            return error
        contract = seed.load_contract(deal_id)
        return contract if contract else {"ok": False, "error": "unknown deal"}

    @mcp.tool
    def get_crm_record(
        deal_id: Annotated[str, Field(description="Canonical deal identifier, such as acme or globex.")],
    ) -> JsonObject:
        """Fetch the current CRM record. Returns current CRM fields, which may be stale."""
        conn = conn_provider()
        _, error = _require_agent_tool(conn, agent_id_provider, "get_crm_record")
        if error:
            return error
        record = database.get_crm(conn, deal_id)
        return record if record else {"ok": False, "error": "unknown deal"}

    @mcp.tool
    def retrieve_context(
        query: Annotated[str, Field(description="Search query describing relevant reconciliation lessons.")],
        memory_type: Annotated[str | None, Field(description="Optional memory type filter.")] = None,
        limit: Annotated[int, Field(description="Maximum number of memories to return.")] = 5,
    ) -> JsonObject:
        """Retrieve reranked memories plus active policy rows. Returns {memories, policy, count}."""
        conn = conn_provider()
        agent, error = _require_agent_tool(conn, agent_id_provider, "retrieve_context")
        if error or agent is None:
            return error or _deny("unknown agent")
        memories = context.retrieve(conn, agent.id, query, memory_type, limit)
        return {
            "memories": [memory.model_dump(mode="json") for memory in memories],
            "policy": [rule.model_dump(mode="json") for rule in database.list_policy(conn)],
            "count": len(memories),
        }

    @mcp.tool
    def route_for_approval(
        deal_id: Annotated[str, Field(description="Deal identifier for the contract/CRM discrepancy.")],
        amount_usd: Annotated[float, Field(description="Absolute dollar impact of the discrepancy.")],
        change_type: Annotated[ChangeType, Field(description="Policy category for approval routing.")],
        summary: Annotated[str, Field(description="Brief explanation of what differs and why approval is needed.")],
    ) -> JsonObject:
        """Route a material discrepancy. Returns approval_request_id, approval_status, route_to, approvals."""
        conn = conn_provider()
        _, error = _require_agent_tool(conn, agent_id_provider, "route_for_approval")
        if error:
            return error
        discrepancy = {"deal_id": deal_id, "amount_usd": amount_usd, "change_type": change_type}
        policy_rules = database.list_policy(conn)
        route_to = governance.route(discrepancy, policy_rules)
        gate = ensure_method_approved(
            conn,
            "crm.write",
            {"tier": PermissionTier.ANALYST, "deal_id": deal_id, "discrepancy": discrepancy},
            policy_rules=policy_rules,
        )
        payload = dict(gate.payload)
        payload["route_to"] = route_to
        payload["status"] = payload.get("approval_status", ApprovalStatus.PENDING)
        payload["summary"] = summary
        return payload

    @mcp.tool
    def get_approval_status(
        approval_request_id: Annotated[str, Field(description="Approval request ID from route_for_approval or write_crm.")],
    ) -> JsonObject:
        """Poll an approval request. Returns aggregate approval_status and approval rows, without tokens."""
        conn = conn_provider()
        _, error = _require_agent_tool(conn, agent_id_provider, "get_approval_status")
        if error:
            return error
        return _approval_status_payload(conn, approval_request_id)

    @mcp.tool
    def write_crm(
        deal_id: Annotated[str, Field(description="Canonical deal identifier whose CRM record should be corrected.")],
        fields: Annotated[JsonObject, Field(description="Only corrected CRM fields to write, keyed by field name.")],
        discrepancy: Annotated[WriteDiscrepancy, Field(description="Material discrepancy justifying the correction.")],
        approval_request_id: Annotated[
            str | None,
            Field(description="Only provide when retrying after get_approval_status reports approval."),
        ] = None,
    ) -> JsonObject:
        """Request or apply a CRM correction through the service approval gate."""
        conn = conn_provider()
        agent, error = _require_agent_tool(conn, agent_id_provider, "write_crm")
        if error or agent is None:
            return error or _deny("unknown agent")
        discrepancy_payload = discrepancy.model_dump(mode="json")
        gate = ensure_method_approved(
            conn,
            "crm.write",
            {"tier": agent.permission_tier, "deal_id": deal_id, "discrepancy": discrepancy_payload},
            approval_request_id,
        )
        if not gate.allowed:
            return gate.payload
        record = database.get_crm(conn, deal_id) or {}
        record.update(fields)
        database.upsert_crm(conn, deal_id, record)
        return {**gate.payload, "crm": record}

    @mcp.tool
    def store_memory(
        content: Annotated[str, Field(description="Specific reusable lesson or pattern to remember.")],
        memory_type: Annotated[MemoryTypeName, Field(description="Category of memory to persist.")] = "lesson",
        metadata: Annotated[JsonObject | None, Field(description="Optional JSON metadata for the memory.")] = None,
    ) -> JsonObject:
        """Store a learned reconciliation lesson. Returns {stored: true, memory_id}."""
        conn = conn_provider()
        agent, error = _require_agent_tool(conn, agent_id_provider, "store_memory")
        if error or agent is None:
            return error or _deny("unknown agent")
        session_id = _provided_or_header(session_id_provider, SESSION_ID_HEADER)
        if not session_id:
            return _deny(f"missing {SESSION_ID_HEADER}")
        memory = Memory(
            session_id=session_id,
            agent_id=agent.id,
            type=MemoryType.PRICING_FIELD_RULE if memory_type == "lesson" else memory_type,
            content=content,
            metadata=metadata or {},
            embedding=context.embed_text(content),
        )
        database.insert_memory(conn, memory)
        return {"stored": True, "memory_id": memory.id}

    return mcp
