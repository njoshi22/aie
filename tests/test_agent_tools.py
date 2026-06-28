from __future__ import annotations

from typing import cast

from agent.tools import get_tools_for_tier


def _names(tier: str) -> set[object]:
    return {tool["name"] for tool in get_tools_for_tier(tier)}


def _tool(tier: str, name: str) -> dict[str, object]:
    for tool in get_tools_for_tier(tier):
        if tool["name"] == name:
            return tool
    raise AssertionError(name)


def _tool_properties(tier: str, name: str) -> dict[str, object]:
    parameters = _tool(tier, name).get("parameters")
    assert isinstance(parameters, dict)
    properties = parameters.get("properties")
    assert isinstance(properties, dict)
    return cast(dict[str, object], properties)


def test_observer_tools_are_read_and_route_only() -> None:
    names = _names("observer")
    assert {"get_contract", "get_crm_record", "retrieve_context", "route_for_approval"} <= names
    assert "write_crm" not in names
    assert "store_memory" not in names


def test_analyst_can_poll_and_write_after_approval() -> None:
    names = _names("analyst")
    assert {"get_approval_status", "write_crm", "store_memory"} <= names

    write_properties = _tool_properties("analyst", "write_crm")
    assert "approval_request_id" in write_properties
    assert "approval_id" not in write_properties

    status_properties = _tool_properties("analyst", "get_approval_status")
    assert "approval_request_id" in status_properties
    assert "approval_id" not in status_properties


def test_autonomous_has_same_write_surface_as_analyst() -> None:
    names = _names("autonomous")
    assert {"get_approval_status", "write_crm", "store_memory"} <= names
