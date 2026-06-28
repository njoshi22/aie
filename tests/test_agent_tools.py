from __future__ import annotations

from typing import cast

import pytest

from agent.tools import get_tools_for_allowed_names


def _names(allowed_tools: list[str]) -> list[object]:
    return [tool["name"] for tool in get_tools_for_allowed_names(allowed_tools)]


def _tool(allowed_tools: list[str], name: str) -> dict[str, object]:
    for tool in get_tools_for_allowed_names(allowed_tools):
        if tool["name"] == name:
            return tool
    raise AssertionError(name)


def _tool_properties(allowed_tools: list[str], name: str) -> dict[str, object]:
    parameters = _tool(allowed_tools, name).get("parameters")
    assert isinstance(parameters, dict)
    properties = parameters.get("properties")
    assert isinstance(properties, dict)
    return cast(dict[str, object], properties)


def _description(allowed_tools: list[str], name: str) -> str:
    description = _tool(allowed_tools, name).get("description")
    assert isinstance(description, str)
    return description


def _object_property(properties: dict[str, object], name: str) -> dict[str, object]:
    value = properties[name]
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


def test_tool_adapter_filters_service_allowed_tools_without_tier_policy() -> None:
    names = _names(["route_for_approval", "get_contract", "log_outcome"])

    assert names == ["get_contract", "route_for_approval"]
    assert "write_crm" not in names


def test_tool_adapter_exposes_write_surface_when_service_allows_it() -> None:
    allowed_tools = ["get_approval_status", "write_crm", "store_memory"]
    names = _names(allowed_tools)

    assert names == ["get_approval_status", "write_crm", "store_memory"]

    write_properties = _tool_properties(allowed_tools, "write_crm")
    assert "approval_request_id" in write_properties
    assert "approval_id" not in write_properties

    status_properties = _tool_properties(allowed_tools, "get_approval_status")
    assert "approval_request_id" in status_properties
    assert "approval_id" not in status_properties


def test_tool_adapter_fails_on_unknown_service_tool() -> None:
    with pytest.raises(ValueError, match="unknown allowed tool"):
        get_tools_for_allowed_names(["get_contract", "delete_policy"])


def test_read_tools_document_required_deal_id_parameter() -> None:
    allowed_tools = ["get_contract", "get_crm_record"]

    for tool_name in allowed_tools:
        properties = _tool_properties(allowed_tools, tool_name)
        deal_id = _object_property(properties, "deal_id")
        assert deal_id["type"] == "string"
        assert "deal identifier" in str(deal_id["description"])


def test_route_for_approval_schema_documents_inputs_and_result_contract() -> None:
    allowed_tools = ["route_for_approval"]
    properties = _tool_properties(allowed_tools, "route_for_approval")

    assert _object_property(properties, "change_type")["enum"] == [
        "schedule_change",
        "term_change",
        "rounding",
        "discount_over_authority",
    ]
    assert "agent_id" not in properties
    assert "source of truth" in str(_object_property(properties, "deal_id")["description"])
    assert "absolute dollar impact" in str(_object_property(properties, "amount_usd")["description"]).lower()
    assert "why approval is needed" in str(_object_property(properties, "summary")["description"])

    description = _description(allowed_tools, "route_for_approval")
    assert "approval_request_id" in description
    assert "approval_status" in description
    assert "approvals" in description
    assert "token" in description


def test_write_crm_schema_documents_nested_discrepancy_and_result_contract() -> None:
    allowed_tools = ["write_crm"]
    properties = _tool_properties(allowed_tools, "write_crm")

    fields = _object_property(properties, "fields")
    assert fields["type"] == "object"
    assert "corrected CRM fields" in str(fields["description"])

    discrepancy = _object_property(properties, "discrepancy")
    assert discrepancy["type"] == "object"
    assert discrepancy["required"] == ["deal_id", "amount_usd", "change_type", "summary"]
    discrepancy_properties = discrepancy["properties"]
    assert isinstance(discrepancy_properties, dict)
    discrepancy_change_type = _object_property(cast(dict[str, object], discrepancy_properties), "change_type")
    assert discrepancy_change_type["enum"] == ["schedule_change", "term_change", "rounding", "discount_over_authority"]

    approval_request_id = _object_property(properties, "approval_request_id")
    assert "retry after get_approval_status" in str(approval_request_id["description"])

    description = _description(allowed_tools, "write_crm")
    assert "approval_required" in description
    assert "approval_request_id" in description
    assert "crm" in description


def test_memory_and_approval_status_schemas_document_outputs() -> None:
    allowed_tools = ["retrieve_context", "store_memory", "get_approval_status"]

    retrieve_description = _description(allowed_tools, "retrieve_context")
    assert "memories" in retrieve_description
    assert "policy" in retrieve_description
    assert "count" in retrieve_description

    store_description = _description(allowed_tools, "store_memory")
    assert "memory_id" in store_description

    status_properties = _tool_properties(allowed_tools, "get_approval_status")
    assert "approval request identifier" in str(_object_property(status_properties, "approval_request_id")["description"])
    status_description = _description(allowed_tools, "get_approval_status")
    assert "approval_status" in status_description
    assert "tokens" in status_description
