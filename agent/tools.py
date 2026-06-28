"""Tool definitions for Antigravity agent — tier-scoped.

Each tool is a dict matching Antigravity's Interactions API format:
  {"type": "function", "name": ..., "description": ..., "parameters": ...}
"""

ToolDefinition = dict[str, object]


GET_CONTRACT: ToolDefinition = {
    "type": "function",
    "name": "get_contract",
    "description": "Fetch the signed contract/order form for a deal.",
    "parameters": {
        "type": "object",
        "properties": {
            "deal_id": {"type": "string"},
        },
        "required": ["deal_id"],
    },
}

GET_CRM_RECORD: ToolDefinition = {
    "type": "function",
    "name": "get_crm_record",
    "description": "Fetch the current CRM record for a deal.",
    "parameters": {
        "type": "object",
        "properties": {
            "deal_id": {"type": "string"},
        },
        "required": ["deal_id"],
    },
}

RETRIEVE_CONTEXT: ToolDefinition = {
    "type": "function",
    "name": "retrieve_context",
    "description": (
        "Search RevMem for relevant memories and lessons from past "
        "reconciliation sessions. Returns {memories: [...], policy: [...], count: N}."
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
        "sessions benefit from it. Use when you discover a pattern worth remembering."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "The lesson or pattern to remember",
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
        "of authority policy. Returns the approval route and status."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "deal_id": {"type": "string"},
            "amount_usd": {
                "type": "number",
                "description": "Dollar amount of the discrepancy",
            },
            "change_type": {
                "type": "string",
                "description": "Type of change: schedule_change, rounding, discount_over_authority",
            },
            "summary": {
                "type": "string",
                "description": "Brief description of the discrepancy",
            },
        },
        "required": ["deal_id", "amount_usd", "change_type", "summary"],
    },
}


GET_APPROVAL_STATUS: ToolDefinition = {
    "type": "function",
    "name": "get_approval_status",
    "description": "Poll an approval request by approval_id. Does not return approval tokens.",
    "parameters": {
        "type": "object",
        "properties": {
            "approval_id": {"type": "string"},
        },
        "required": ["approval_id"],
    },
}

WRITE_CRM: ToolDefinition = {
    "type": "function",
    "name": "write_crm",
    "description": (
        "Write CRM corrections after server authorization. Requires ANALYST or "
        "AUTONOMOUS tier and either an approved approval_id or a server-allowed "
        "autonomous correction."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "deal_id": {"type": "string"},
            "fields": {"type": "object"},
            "discrepancy": {"type": "object"},
            "approval_id": {"type": "string"},
        },
        "required": ["deal_id", "fields", "discrepancy"],
    },
}


def get_tools_for_tier(tier: str) -> list[ToolDefinition]:
    """Return tool list scoped to the agent's permission tier."""
    observer_tools = [GET_CONTRACT, GET_CRM_RECORD, RETRIEVE_CONTEXT, ROUTE_FOR_APPROVAL]
    if tier == "observer":
        return observer_tools
    elif tier == "analyst":
        return observer_tools + [GET_APPROVAL_STATUS, WRITE_CRM, STORE_MEMORY]
    else:  # autonomous
        return observer_tools + [GET_APPROVAL_STATUS, WRITE_CRM, STORE_MEMORY]
