from __future__ import annotations

import asyncio
from typing import Any, cast

from fastmcp import Client
from fastapi.testclient import TestClient

from api.main import create_app
from api.mcp_server import create_revmem_mcp
from core import database
from core.models import Agent, PermissionTier
from data import seed


def _seeded_conn(tmp_path):
    conn = database.get_connection(tmp_path / "mcp.db")
    database.init_db(conn)
    seed.seed(conn)
    return conn


def _agent(conn, tier: str) -> Agent:
    agent = Agent(name=f"MCP {tier}", permission_tier=tier)
    database.insert_agent(conn, agent)
    return agent


def test_fastapi_mounts_service_mcp(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("REVMEM_DB", str(tmp_path / "api.db"))
    app = create_app()

    with TestClient(app):
        mounted_paths = {getattr(route, "path", "") for route in app.routes}

    assert "/mcp" in mounted_paths


def test_mcp_tool_discovery_documents_model_supplied_args(tmp_path) -> None:
    conn = _seeded_conn(tmp_path)
    agent = _agent(conn, PermissionTier.ANALYST)
    mcp = create_revmem_mcp(lambda: conn, agent_id_provider=lambda: agent.id)

    async def run() -> None:
        async with Client(mcp) as client:
            tools = await client.list_tools()

        by_name = {tool.name: tool for tool in tools}
        assert "route_for_approval" in by_name
        route_schema = by_name["route_for_approval"].inputSchema
        route_properties = cast(dict[str, Any], route_schema["properties"])
        assert "agent_id" not in route_properties
        assert route_properties["change_type"]["enum"] == [
            "schedule_change",
            "term_change",
            "rounding",
            "discount_over_authority",
        ]

        write_schema = by_name["write_crm"].inputSchema
        write_properties = cast(dict[str, Any], write_schema["properties"])
        discrepancy = cast(dict[str, Any], write_properties["discrepancy"])
        assert discrepancy["required"] == ["deal_id", "amount_usd", "change_type", "summary"]

    try:
        asyncio.run(run())
    finally:
        conn.close()


def test_mcp_tool_discovery_filters_tools_by_agent_reputation(tmp_path) -> None:
    conn = _seeded_conn(tmp_path)
    observer = _agent(conn, PermissionTier.OBSERVER)
    analyst = _agent(conn, PermissionTier.ANALYST)
    autonomous = _agent(conn, PermissionTier.AUTONOMOUS)
    current_agent_id = observer.id
    mcp = create_revmem_mcp(lambda: conn, agent_id_provider=lambda: current_agent_id)

    async def discovered_tool_names() -> set[str]:
        async with Client(mcp) as client:
            return {tool.name for tool in await client.list_tools()}

    try:
        observer_tools = asyncio.run(discovered_tool_names())
        current_agent_id = analyst.id
        analyst_tools = asyncio.run(discovered_tool_names())
        current_agent_id = autonomous.id
        autonomous_tools = asyncio.run(discovered_tool_names())
    finally:
        conn.close()

    assert observer_tools == {"get_contract", "get_crm_record", "retrieve_context", "route_for_approval"}
    assert analyst_tools == {
        "get_contract",
        "get_crm_record",
        "retrieve_context",
        "route_for_approval",
        "get_approval_status",
        "write_crm",
        "store_memory",
    }
    assert autonomous_tools == analyst_tools


def test_mcp_route_for_approval_uses_db_policy_and_agent_identity(tmp_path) -> None:
    conn = _seeded_conn(tmp_path)
    agent = _agent(conn, PermissionTier.OBSERVER)
    rule = database.get_policy(conn, "DOA-003")
    assert rule is not None
    rule.route_to = "finance_admin"
    database.upsert_policy(conn, rule)
    mcp = create_revmem_mcp(lambda: conn, agent_id_provider=lambda: agent.id)

    async def run() -> None:
        async with Client(mcp) as client:
            result = await client.call_tool(
                "route_for_approval",
                {
                    "deal_id": "acme",
                    "amount_usd": 40000,
                    "change_type": "schedule_change",
                    "summary": "Annual schedule differs from signed contract.",
                },
            )

        assert result.data["route_to"] == "finance_admin"
        assert result.data["approval_required"] is True
        assert [approval["role"] for approval in result.data["approvals"]] == ["finance_admin"]

    try:
        asyncio.run(run())
    finally:
        conn.close()


def test_mcp_write_crm_is_denied_from_db_policy_for_observer(tmp_path) -> None:
    conn = _seeded_conn(tmp_path)
    agent = _agent(conn, PermissionTier.OBSERVER)
    mcp = create_revmem_mcp(lambda: conn, agent_id_provider=lambda: agent.id)

    async def run() -> None:
        async with Client(mcp) as client:
            result = await client.call_tool(
                "write_crm",
                {
                    "deal_id": "acme",
                    "fields": {"annual_schedule_usd": [100000, 150000, 200000]},
                    "discrepancy": {
                        "deal_id": "acme",
                        "amount_usd": 40000,
                        "change_type": "schedule_change",
                        "summary": "Annual schedule differs from signed contract.",
                    },
                },
            )

        assert result.data["ok"] is False
        assert result.data["decision"] == "deny"
        assert "cannot write_crm" in result.data["reason"]

    try:
        asyncio.run(run())
    finally:
        conn.close()
