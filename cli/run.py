"""RevMem agent-working CLI - the live terminal transcript (the demo's hero).

Scaffold: replays a reconciliation session and drives the single CFO email
approval gate. The mock data and the simulated agent loop are placeholders for
Person A's Antigravity agent and Person B's RevMem API (see TODOs).

Run:
    uv run python -m cli.run                  # S3 with live CFO approval (default)
    uv run python -m cli.run --session s1     # S1 cold start (no approval)
    uv run python -m cli.run --no-wait        # skip polling (print link and exit)

For the live approval gate, also run the approval endpoint:
    uv run uvicorn notify.approve:app --port 8000
"""

from __future__ import annotations

import argparse
import time

from rich.console import Console

from cli import render
from notify import email
from notify.approve import create_approval, wait_for_approval

console = Console()

# --- Mock scenario data -------------------------------------------------------
# TODO(integration): fetch via RevMem tools get_contract/get_crm_record and the
# Context Engine instead of these literals. Mirrors ARCHITECTURE.md hero mismatch.

ACME_FIELDS = [
    {"field": "Seats", "contract": "1,000", "crm": "1,000", "verdict": "match"},
    {"field": "TCV", "contract": "$450,000", "crm": "$450,000", "verdict": "match"},
    {"field": "Annual schedule", "contract": "$100k / $150k / $200k", "crm": "$150k / $150k / $150k", "verdict": "material"},
    {"field": "Discount", "contract": "10%", "crm": "10%", "verdict": "match"},
    {"field": "Y1 monthly invoice", "contract": "$8,333.33", "crm": "$8,333.00", "verdict": "immaterial"},
]

SCENARIOS = {
    "s1": {
        "session_name": "Session 1 - cold start",
        "deal_id": "ACME-2026",
        "task": "Reconcile signed contract against Salesforce; route discrepancies.",
        "fields": ACME_FIELDS,
        "rep_before": 0.10,
        "rep_after": 0.20,
        "tier": "observer",
        "memory": None,  # genuinely nothing learned yet
        "needs_approval": False,
        "outcome": {"material_caught": "0/1", "false_escalations": 1, "accuracy": 0.0},
    },
    "s3": {
        "session_name": "Session 3 - live (ANALYST)",
        "deal_id": "GLOBEX-2026",
        "task": "Reconcile signed contract against Salesforce; route discrepancies.",
        # Globex: same ramp archetype, different numbers (lesson generalizes).
        "fields": [
            {"field": "Seats", "contract": "800", "crm": "800", "verdict": "match"},
            {"field": "TCV", "contract": "$360,000", "crm": "$360,000", "verdict": "match"},
            {"field": "Annual schedule", "contract": "$80k / $120k / $160k", "crm": "$120k / $120k / $120k", "verdict": "material"},
            {"field": "Discount", "contract": "20%", "crm": "20%", "verdict": "match"},
            {"field": "Y1 monthly invoice", "contract": "$6,666.67", "crm": "$6,666.00", "verdict": "immaterial"},
        ],
        "rep_before": 0.50,
        "rep_after": 0.65,
        "tier": "analyst",
        "memory": "TCV parity is insufficient for ramped deals; reconcile the annual schedule.",
        "needs_approval": True,
        "discrepancy": "Year-1 revenue understated: CRM flat $120k vs ramped $80k schedule.",
        "recommended_fix": "Set CRM annual schedule to $80k / $120k / $160k (match signed contract).",
        "amount_usd": 40000.0,
        "approver_email": "cfo@example.com",  # TODO: from policy / env
        "outcome": {"material_caught": "1/1", "false_escalations": 0, "accuracy": 1.0},
    },
}


def _beat(seconds: float = 0.6) -> None:
    """Small pause so the transcript reads as a live agent working."""
    time.sleep(seconds)


def tier_for(score: float) -> str:
    """Permission tier from reputation (ARCHITECTURE.md thresholds)."""
    return "observer" if score < 0.3 else "analyst" if score < 0.6 else "autonomous"


def run_session(name: str, wait: bool = True) -> None:
    sc = SCENARIOS[name]
    console.print()
    console.print(render.session_header(sc["session_name"], "RevOps Finance Agent", sc["task"]))
    console.print(render.reputation_bar(sc["rep_before"], tier_for(sc["rep_before"])))
    console.print()

    console.print(render.step(f"get_contract({sc['deal_id']})  +  get_crm_record(...)", status="ok"))
    _beat()

    if sc["memory"]:
        console.print(render.step("retrieve_context(...)", f'recalled: "{sc["memory"]}"', status="ok"))
    else:
        console.print(render.step("retrieve_context(...)", "no prior memories - cold start", status="warn"))
    _beat()

    console.print()
    console.print(render.diff_table(sc["fields"]))
    console.print()

    # Reconcile each non-matching field according to tier behavior.
    for f in sc["fields"]:
        if f["verdict"] == "immaterial":
            if sc["tier"] == "observer":
                console.print(render.step(f"{f['field']}: rounding artifact", "ESCALATED (cold agent over-flags)", status="warn"))
            else:
                console.print(render.step(f"{f['field']}: rounding artifact", "dismissed as immaterial", status="ok"))
            _beat(0.4)
        elif f["verdict"] == "material":
            if sc["tier"] == "observer":
                console.print(render.step(f"{f['field']}: ramp restructuring", "MISSED (no learned context)", status="err"))
            else:
                console.print(render.step(f"{f['field']}: ramp restructuring", "caught - material, routing for approval", status="ok"))
            _beat(0.4)

    if not sc["needs_approval"]:
        console.print()
        console.print(render.outcome_panel(sc["outcome"]))
        console.print(render.reputation_bar(sc["rep_after"], tier_for(sc["rep_after"])))
        console.print("\n[grey70]Reviewer correction on this outcome creates the one experiential memory.[/]\n")
        return

    # --- Human-in-the-loop: single CFO email approval -------------------------
    console.print()
    console.print(render.routing_panel(sc["discrepancy"], sc["approver_email"], sc["recommended_fix"]))

    approval = create_approval(
        deal_id=sc["deal_id"],
        approver_email=sc["approver_email"],
        discrepancy=sc["discrepancy"],
        recommended_fix=sc["recommended_fix"],
        amount_usd=sc.get("amount_usd"),
    )
    email.send_approval_email(approval)
    console.print(render.approval_request_panel(sc["approver_email"], approval.approve_url()))

    if not wait:
        console.print(
            f"\n[grey70]--no-wait: approve at the link above, confirm with"
            f"\n  curl -s {approval.status_url()}"
            f"\nThis run will not resume (re-running mints a new approval). Use the default mode for the full gate.[/]\n"
        )
        return

    try:
        with console.status("[yellow]waiting for CFO approval...[/]", spinner="dots"):
            decided = wait_for_approval(approval.id)
    except TimeoutError:
        console.print("\n[red]Approval timed out - leaving CRM unchanged.[/]\n")
        return

    if decided.status == "approved":
        console.print(render.step("CFO approved", status="ok"))
        _beat()
        console.print(render.step(f"write_crm({sc['deal_id']}, corrected_fields)", "ANALYST permission - executed", status="ok"))
        console.print()
        console.print(render.outcome_panel(sc["outcome"]))
        console.print(render.reputation_bar(sc["rep_after"], tier_for(sc["rep_after"])))
        console.print("\n[green]Reconciled. Reputation rises -> next deal could auto-reconcile unattended.[/]\n")
    else:
        console.print(render.step("CFO rejected", "CRM left unchanged", status="warn"))


def main() -> None:
    parser = argparse.ArgumentParser(description="RevMem agent-working CLI (scaffold).")
    parser.add_argument("--session", default="s3", choices=sorted(SCENARIOS), help="scenario to replay")
    parser.add_argument("--no-wait", action="store_true", help="print approve link and exit instead of polling")
    args = parser.parse_args()
    run_session(args.session, wait=not args.no_wait)


if __name__ == "__main__":
    main()
