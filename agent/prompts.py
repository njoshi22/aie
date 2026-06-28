"""Prompt templates for contract reconciliation sessions.

The agent is given no data inline — it must obtain everything through the
service-layer function tools (``retrieve_context``, ``get_contract``,
``get_crm_record``) and act through governed tools (``route_for_approval``,
``write_crm``). This keeps the agent on the audited service layer instead of
reading sandbox files.
"""

from collections.abc import Iterable


def build_reconciliation_prompt(deal_id: str, allowed_tool_names: Iterable[str]) -> str:
    allowed_tools = set(allowed_tool_names)
    prompt = (
        f"Reconcile deal '{deal_id}' (signed contract vs. CRM record).\n\n"
        "No data is included in this prompt — obtain everything by calling your tools.\n\n"
        "STEPS:\n"
        "1. Call retrieve_context first to load lessons from past reconciliations AND the "
        'delegation-of-authority policy (returned under "policy"). Apply any retrieved lessons.\n'
        f'2. Call get_contract with deal_id "{deal_id}" — the signed contract is the source of truth.\n'
        f'3. Call get_crm_record with deal_id "{deal_id}" — the current (possibly stale) CRM record.\n'
        "4. Compare every pricing field individually between the contract and the CRM record.\n"
        "5. Classify each mismatch material or immaterial using the policy from retrieve_context "
        "(differences under $1 are immaterial rounding).\n"
    )

    if "write_crm" in allowed_tools:
        prompt += (
            "6. For every MATERIAL discrepancy, call write_crm with the corrected fields and the "
            "discrepancy. If write_crm returns approval_required, poll get_approval_status with the "
            "approval_request_id, then retry write_crm only after approval using the exact approved "
            "correction and approval_request_id. Use route_for_approval if that tool is available and "
            "a change exceeds your authority.\n"
            "\nYour service-authorized tool set includes write_crm: request CRM corrections through "
            "the governed service method, and auto-dismiss immaterial differences (< $1).\n"
        )
    elif "route_for_approval" in allowed_tools:
        prompt += (
            "6. For every MATERIAL discrepancy, call route_for_approval (deal_id, amount_usd, "
            "change_type, summary) to escalate it to the correct approver per policy.\n"
            "\nYour service-authorized tool set does not include a CRM-write tool: you may NOT write to CRM. "
            "Escalate material discrepancies via route_for_approval, and classify sub-$1 rounding "
            "differences as immaterial.\n"
        )
    else:
        prompt += (
            "6. No CRM write or approval-routing tool is available. Do not claim that a material "
            "discrepancy was routed or corrected unless a governed tool call actually does it.\n"
        )

    prompt += (
        "7. Do NOT merely describe routing in text — the governed tool in step 6 MUST actually be "
        "called for every material discrepancy.\n"
        "8. Output your final analysis as the JSON object specified in AGENTS.md (the fields_compared schema).\n"
        "\nIf a reviewer later gives feedback, call store_memory to persist the lesson for future reconciliations.\n"
    )

    return prompt


def build_feedback_prompt(feedback_text: str) -> str:
    return (
        "A human reviewer has provided the following feedback on your last "
        f"reconciliation:\n\n{feedback_text}\n\n"
        "Please:\n"
        "1. Acknowledge the feedback.\n"
        "2. Store the key lesson using store_memory (type: lesson) so you "
        "can apply it in future reconciliations.\n"
        "3. Confirm what you've learned.\n"
    )
