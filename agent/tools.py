"""Tool definitions for Antigravity agent — tier-scoped.

Each tool is a dict matching Antigravity's Interactions API format:
  {"type": "function", "name": ..., "description": ..., "parameters": ...}
"""

RETRIEVE_CONTEXT = {
    "type": "function",
    "name": "retrieve_context",
    "description": (
        "Search RevMem for relevant memories and lessons from past "
        "reconciliation sessions. Returns {memories: [...], count: N}."
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

STORE_MEMORY = {
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

ROUTE_FOR_APPROVAL = {
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
                "description": "Type of change: schedule_mismatch, rounding, discount_over_authority",
            },
            "summary": {
                "type": "string",
                "description": "Brief description of the discrepancy",
            },
        },
        "required": ["deal_id", "amount_usd", "change_type", "summary"],
    },
}


def get_tools_for_tier(tier: str) -> list[dict]:
    """Return tool list scoped to the agent's permission tier."""
    if tier == "observer":
        return [RETRIEVE_CONTEXT, ROUTE_FOR_APPROVAL]
    elif tier == "analyst":
        return [RETRIEVE_CONTEXT, STORE_MEMORY, ROUTE_FOR_APPROVAL]
    else:  # autonomous
        return [RETRIEVE_CONTEXT, STORE_MEMORY, ROUTE_FOR_APPROVAL]
