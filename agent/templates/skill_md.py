from pathlib import Path

_SKILL_MD_PATH = Path(__file__).resolve().parent.parent.parent / ".agents" / "skills" / "reconciliation" / "SKILL.md"

_BASE_SKILL = _SKILL_MD_PATH.read_text()


def generate_skill_md(tier: str) -> str:
    """Generate a tier-scoped SKILL.md from the base file.

    The base .agents/skills/reconciliation/SKILL.md contains all actions.
    This function adjusts the available actions and tier section based on
    the agent's current permission tier.
    """
    skills = """\
---
name: revops-reconciliation
description: Contract-CRM reconciliation skills
---

# RevOps Reconciliation Skills

## Available Actions

- **read_contract**: Read and parse signed contract pricing fields
- **read_crm**: Read the CRM (Salesforce) record for a deal
- **read_policy**: Read the delegation-of-authority routing policy
- **report_discrepancy**: Flag a pricing discrepancy with a recommended approver
"""

    if tier in ("analyst", "autonomous"):
        skills += """\
- **retrieve_context**: Query RevMem for relevant experiential memories from past reconciliations
- **write_crm**: Request or apply CRM corrections through the service approval gate (requires ANALYST tier)
- **store_memory**: Persist a learned pattern or lesson to RevMem (requires ANALYST tier)
"""

    if tier == "autonomous":
        skills += """\
- **auto_reconcile**: Automatically fix policy-covered corrections without human approval (requires AUTONOMOUS tier)
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
