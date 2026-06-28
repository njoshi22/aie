from __future__ import annotations

from agent.tools import get_tools_for_tier


def _names(tier: str) -> set[object]:
    return {tool["name"] for tool in get_tools_for_tier(tier)}


def test_observer_tools_are_read_and_route_only() -> None:
    names = _names("observer")
    assert {"get_contract", "get_crm_record", "retrieve_context", "route_for_approval"} <= names
    assert "write_crm" not in names
    assert "store_memory" not in names


def test_analyst_can_poll_and_write_after_approval() -> None:
    names = _names("analyst")
    assert {"get_approval_status", "write_crm", "store_memory"} <= names


def test_autonomous_has_same_write_surface_as_analyst() -> None:
    names = _names("autonomous")
    assert {"get_approval_status", "write_crm", "store_memory"} <= names
