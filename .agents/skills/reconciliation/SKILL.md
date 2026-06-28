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
- **retrieve_context**: Query RevMem for relevant experiential memories from past reconciliations
- **write_crm**: Request or apply CRM corrections through the service approval gate (requires ANALYST tier)
- **store_memory**: Persist a learned pattern or lesson to RevMem (requires ANALYST tier)
- **auto_reconcile**: Automatically fix policy-covered corrections without human approval (requires AUTONOMOUS tier)

## Current Permission Tier: ANALYST

You may read data, flag discrepancies, retry approved CRM corrections with approval_request_id, and store learned patterns. Auto-dismiss immaterial differences (< $1). Escalate material issues per policy.
