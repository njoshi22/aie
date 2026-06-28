"""Prompt templates for contract reconciliation sessions."""
import json


def build_reconciliation_prompt(
    contract: dict,
    crm: dict,
    policy: dict,
    memories: list[dict],
    tier: str,
) -> str:
    prompt = (
        "You are performing a contract-CRM reconciliation.\n\n"
        f"SIGNED CONTRACT:\n{json.dumps(contract, indent=2)}\n\n"
        f"CRM RECORD:\n{json.dumps(crm, indent=2)}\n\n"
        f"DELEGATION OF AUTHORITY POLICY:\n{json.dumps(policy, indent=2)}\n\n"
    )

    if memories:
        prompt += "RELEVANT LESSONS FROM PAST RECONCILIATIONS:\n"
        for mem in memories:
            prompt += f"- {mem.get('content', '')}\n"
        prompt += "\nUse these lessons to inform your analysis.\n\n"

    retrieve_instruction = (
        "1. First, call retrieve_context to check for lessons from past reconciliations.\n"
        if not memories else
        "1. Use the relevant lessons already provided; do not call retrieve_context unless the context is missing.\n"
    )

    prompt += (
        "INSTRUCTIONS:\n"
        f"{retrieve_instruction}"
        "2. Compare every pricing field between the contract and CRM record.\n"
        "3. For each field, state whether it matches or not.\n"
        "4. For mismatches, classify as material or immaterial.\n"
        "5. Route material discrepancies to the correct approver using the returned policy.\n"
        "6. If you receive an approval_id, call get_approval_status with that id.\n"
        "7. If status is approved and your tier allows writes, call write_crm with the exact "
        "approved discrepancy and corrected fields. If status is pending or rejected, do not write.\n"
        "8. Output your analysis as the JSON format specified in AGENTS.md.\n"
    )

    if tier == "observer":
        prompt += (
            "\nYou are in OBSERVER mode. You may not write to CRM. "
            "Escalate material discrepancies, but classify sub-$1 rounding "
            "differences as immaterial instead of escalating them.\n"
        )
    elif tier == "analyst":
        prompt += (
            "\nYou are in ANALYST mode. You may auto-dismiss immaterial differences "
            "(under $1) and recommend CRM corrections for approval.\n"
        )
    elif tier == "autonomous":
        prompt += (
            "\nYou are in AUTONOMOUS mode. You may auto-reconcile policy-covered "
            "corrections and only escalate genuine judgment calls.\n"
        )

    return prompt


COLD_START_FIELDS = {
    "deal_id", "customer", "product", "seats", "tcv_usd",
    "term_years", "discount_pct", "y1_monthly_invoice_usd",
}


def _summary_view(record: dict) -> dict:
    """S1 agent only sees summary-level fields. No schedule, no notes, no metadata."""
    return {k: v for k, v in record.items() if k in COLD_START_FIELDS}


def build_cold_start_prompt(contract: dict, crm: dict) -> str:
    """Session 1 prompt — deliberately shallow. No policy, no memories, no tier guidance.

    The annual schedule is stripped from both records. The agent only sees
    summary-level fields (TCV, seats, discount, monthly invoice). This makes
    the "miss" genuine — the data wasn't available, not faked.

    The learning moment in S2: RevMem memory says "TCV parity is insufficient;
    always request and reconcile the annual payment schedule."
    """
    contract_summary = _summary_view(contract)
    crm_summary = _summary_view(crm)

    return (
        "You are a financial analyst performing a standard deal sanity check.\n\n"
        "The system has pulled the following SUMMARY records for this deal. "
        "These are the fields available in the current view.\n\n"
        f"SIGNED CONTRACT (summary view):\n{json.dumps(contract_summary, indent=2)}\n\n"
        f"CRM RECORD (summary view):\n{json.dumps(crm_summary, indent=2)}\n\n"
        "Compare every field shown above. For each field, state match or mismatch.\n"
        "If you find any difference, escalate it — you don't have routing rules yet.\n\n"
        "Output as JSON with fields: deal_id, fields_compared (array of "
        "{field, contract_value, crm_value, match, materiality, diff_usd, "
        "recommended_action, route_to, reasoning}), summary.\n"
    )
