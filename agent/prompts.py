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

    prompt += (
        "\nWhen you receive feedback or corrections from a reviewer, store the "
        "lesson using store_memory so you can apply it in future reconciliations.\n"
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
