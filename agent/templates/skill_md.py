def generate_skill_md(tier: str) -> str:
    """Generate a tier-scoped SKILL.md.

    Action names match the real function tools in ``agent/tools.py`` and the
    tiers mirror ``get_tools_for_tier``. The "How To Work" preamble steers the
    hosted coding agent away from exploring the sandbox filesystem / executing
    code to hunt for tools that are actually provided as function calls.
    """
    skills = """\
---
name: revops-reconciliation
description: Contract-CRM reconciliation skills
---

# RevOps Reconciliation Skills

## How To Work

The actions below are **function tools** provided directly to you — call them as
tools. Do NOT list directories, read arbitrary files, or execute code to look for
CLIs, scripts, databases, or mock APIs: these tools ARE the interface, and the
contract, CRM record, and policy are already included in your task prompt.

## Available Tools

- **get_contract**: Fetch the signed contract / order-form pricing fields for a deal
- **get_crm_record**: Fetch the current CRM (Salesforce) record for a deal
- **retrieve_context**: Query RevMem for relevant lessons from past reconciliations
- **route_for_approval**: Route a material discrepancy to the correct approver per policy
"""

    if tier in ("analyst", "autonomous"):
        skills += """\
- **write_crm**: Request or apply a CRM correction through the service approval gate (ANALYST+)
- **get_approval_status**: Poll an approval request by approval_request_id (ANALYST+)
- **store_memory**: Persist a learned pattern or lesson to RevMem (ANALYST+)
"""

    skills += f"""
## Current Permission Tier: {tier.upper()}
"""

    if tier == "observer":
        skills += """\
You may read data and flag discrepancies, but you CANNOT modify CRM records or store memories. \
Escalate everything — do not attempt to resolve issues yourself.
"""
    elif tier == "analyst":
        skills += """\
You may read data, flag discrepancies, retry approved CRM corrections with approval_request_id, and store learned patterns. \
Auto-dismiss immaterial differences (< $1). Escalate material issues per policy.
"""
    elif tier == "autonomous":
        skills += """\
You may auto-reconcile policy-covered corrections without approval. \
Only escalate genuine judgment calls or items exceeding your authority.
"""

    return skills
