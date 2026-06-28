"""Tool definitions for Antigravity agent.

Each tool is a dict matching Antigravity's Interactions API format:
  {"type": "function", "name": ..., "description": ..., "parameters": ...}
"""

from collections.abc import Iterable

ToolDefinition = dict[str, object]


GET_CONTRACT: ToolDefinition = {
    "type": "function",
    "name": "get_contract",
    "description": (
        "Fetch the signed contract/order form for a deal. Returns the source-of-truth "
        "contract pricing fields for the requested deal_id."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "deal_id": {
                "type": "string",
                "description": "Canonical deal identifier from the reconciliation task, such as acme or globex.",
            },
        },
        "required": ["deal_id"],
    },
}

GET_CRM_RECORD: ToolDefinition = {
    "type": "function",
    "name": "get_crm_record",
    "description": (
        "Fetch the current CRM record for a deal. Returns the current Salesforce/CRM "
        "pricing fields, which may be stale and must be compared against the contract."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "deal_id": {
                "type": "string",
                "description": "Canonical deal identifier from the reconciliation task, such as acme or globex.",
            },
        },
        "required": ["deal_id"],
    },
}

RETRIEVE_CONTEXT: ToolDefinition = {
    "type": "function",
    "name": "retrieve_context",
    "description": (
        "Search RevMem for relevant memories and lessons from past reconciliation "
        "sessions AND the active delegation-of-authority policy. This is how you obtain "
        "the routing policy. Returns {memories: [...], policy: [...], count: N}."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query describing what memories to look for",
            },
        },
        "required": ["query"],
    },
}

STORE_MEMORY: ToolDefinition = {
    "type": "function",
    "name": "store_memory",
    "description": (
        "Save a lesson learned from this reconciliation to RevMem so future "
        "sessions benefit from it. Use when you discover a pattern worth remembering. "
        "Returns {stored: true, memory_id: string}."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "Specific reusable lesson or pattern to remember for future reconciliations.",
            },
            "memory_type": {
                "type": "string",
                "enum": ["lesson", "pattern", "warning"],
                "description": "Category of memory",
            },
        },
        "required": ["content", "memory_type"],
    },
}

ROUTE_FOR_APPROVAL: ToolDefinition = {
    "type": "function",
    "name": "route_for_approval",
    "description": (
        "Route a material discrepancy for human approval per the delegation "
        "of authority policy. The runner injects agent_id; do not provide it. "
        "Returns {approval_required, approval_request_id, approval_status, "
        "route_to, approvals}. It never returns human approval tokens or links; "
        "poll get_approval_status with approval_request_id."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "deal_id": {
                "type": "string",
                "description": "Deal identifier for the source of truth contract and CRM record being reconciled.",
            },
            "amount_usd": {
                "type": "number",
                "description": "Absolute dollar impact of the discrepancy. Use 0 for non-dollar policy exceptions.",
            },
            "change_type": {
                "type": "string",
                "enum": ["schedule_change", "rounding", "discount_over_authority"],
                "description": "Policy category for routing the discrepancy.",
            },
            "summary": {
                "type": "string",
                "description": "Brief explanation of what differs and why approval is needed.",
            },
        },
        "required": ["deal_id", "amount_usd", "change_type", "summary"],
    },
}


GET_APPROVAL_STATUS: ToolDefinition = {
    "type": "function",
    "name": "get_approval_status",
    "description": (
        "Poll an approval request by approval_request_id. Returns {approval_required, "
        "approval_request_id, approval_status, approvals}. Does not return approval tokens."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "approval_request_id": {
                "type": "string",
                "description": "Service approval request identifier returned by route_for_approval or write_crm.",
            },
        },
        "required": ["approval_request_id"],
    },
}

WRITE_CRM: ToolDefinition = {
    "type": "function",
    "name": "write_crm",
    "description": (
        "Write CRM corrections through the service method gate. The service either "
        "executes and returns {ok, decision, approval_required: false, crm}, or "
        "returns {ok: false, decision, approval_required: true, approval_request_id, "
        "approval_status, approvals}. If approval is pending, poll get_approval_status "
        "and retry only after approval using the exact approval_request_id."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "deal_id": {
                "type": "string",
                "description": "Canonical deal identifier whose CRM record should be corrected.",
            },
            "fields": {
                "type": "object",
                "description": "Only the corrected CRM fields to write, keyed by CRM field name.",
            },
            "discrepancy": {
                "type": "object",
                "description": "Material discrepancy that justifies the CRM correction and approval route.",
                "properties": {
                    "deal_id": {
                        "type": "string",
                        "description": "Deal identifier for the discrepancy; should match the top-level deal_id.",
                    },
                    "amount_usd": {
                        "type": "number",
                        "description": "Absolute dollar impact of the discrepancy. Use 0 for non-dollar policy exceptions.",
                    },
                    "change_type": {
                        "type": "string",
                        "enum": ["schedule_change", "rounding", "discount_over_authority"],
                        "description": "Policy category for routing or approving the correction.",
                    },
                    "summary": {
                        "type": "string",
                        "description": "Brief explanation of what differs and why the correction is needed.",
                    },
                },
                "required": ["deal_id", "amount_usd", "change_type", "summary"],
            },
            "approval_request_id": {
                "type": "string",
                "description": "Only provide when retrying after get_approval_status reports the request is approved.",
            },
        },
        "required": ["deal_id", "fields", "discrepancy"],
    },
}


_TOOL_REGISTRY = [
    GET_CONTRACT,
    GET_CRM_RECORD,
    RETRIEVE_CONTEXT,
    ROUTE_FOR_APPROVAL,
    GET_APPROVAL_STATUS,
    WRITE_CRM,
    STORE_MEMORY,
]
_TOOL_BY_NAME = {str(tool["name"]): tool for tool in _TOOL_REGISTRY}
_SERVICE_ACTIONS_WITHOUT_FUNCTION_DECLARATIONS = {"log_outcome"}


def get_tools_for_allowed_names(allowed_tool_names: Iterable[str]) -> list[ToolDefinition]:
    """Return Gemini tool declarations for the service-authorized tool names."""
    allowed = set(allowed_tool_names)
    unknown = allowed - set(_TOOL_BY_NAME) - _SERVICE_ACTIONS_WITHOUT_FUNCTION_DECLARATIONS
    if unknown:
        raise ValueError(f"unknown allowed tool(s) from service: {', '.join(sorted(unknown))}")
    return [tool for tool in _TOOL_REGISTRY if tool["name"] in allowed]
