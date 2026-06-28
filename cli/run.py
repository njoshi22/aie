"""RevMem agent-working CLI - the live terminal transcript (the demo's hero).

Two modes:
  --live          Real Antigravity agent with Rich rendering (requires GEMINI_API_KEY)
  --session s1    Scaffold replay with mock data (no API key needed)

Run:
    uv run python -m cli.run --live                # real agent, Rich UI
    uv run python -m cli.run --live --session 2    # real agent, specific session
    uv run python -m cli.run                       # scaffold S3 with live CFO approval
    uv run python -m cli.run --session s1          # scaffold S1 cold start
    uv run python -m cli.run --no-wait             # skip polling (print link and exit)

For the live approval gate, also run the approval endpoint:
    uv run uvicorn notify.approve:app --port 8000
"""

from __future__ import annotations

import argparse
import json
import time

from rich.console import Console

from cli import render
from notify import email
from notify.approve import create_approval, wait_for_approval

console = Console()

# --- Mock scenario data (scaffold mode) --------------------------------------

ACME_FIELDS = [
    {"field": "Seats", "contract": "1,000", "crm": "1,000", "verdict": "match"},
    {"field": "TCV", "contract": "$450,000", "crm": "$450,000", "verdict": "match"},
    {"field": "Annual schedule", "contract": "$100k / $150k / $200k", "crm": "$150k / $150k / $150k", "verdict": "material"},
    {"field": "Discount", "contract": "10%", "crm": "10%", "verdict": "match"},
    {"field": "Y1 monthly invoice", "contract": "$8,333.33", "crm": "$8,333.00", "verdict": "immaterial"},
]

SCAFFOLD_SCENARIOS = {
    "s1": {
        "session_name": "Session 1 - cold start",
        "deal_id": "ACME-2026",
        "task": "Reconcile signed contract against Salesforce; route discrepancies.",
        "fields": ACME_FIELDS,
        "rep_before": 0.10,
        "rep_after": 0.20,
        "tier": "observer",
        "memory": None,
        "needs_approval": False,
        "outcome": {"material_caught": "0/1", "false_escalations": 1, "accuracy": 0.0},
    },
    "s3": {
        "session_name": "Session 3 - live (ANALYST)",
        "deal_id": "GLOBEX-2026",
        "task": "Reconcile signed contract against Salesforce; route discrepancies.",
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
        "approver_email": "cfo@example.com",
        "outcome": {"material_caught": "1/1", "false_escalations": 0, "accuracy": 1.0},
    },
}


def _beat(seconds: float = 0.6) -> None:
    time.sleep(seconds)


def tier_for(score: float) -> str:
    return "observer" if score < 0.3 else "analyst" if score < 0.6 else "autonomous"


# --- Scaffold mode ------------------------------------------------------------

def run_scaffold(name: str, wait: bool = True) -> None:
    sc = SCAFFOLD_SCENARIOS[name]
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


# --- Live mode (real Antigravity agent + Rich rendering) ----------------------

class RichListener:
    """Renders real agent events through the Rich CLI panels."""

    def __init__(self, wait_for_approvals: bool = True):
        self._wait = wait_for_approvals
        self._deal_id: str = ""
        self._tier: str = ""

    def on_session_start(self, session_number, deal, tier, reputation, task):
        self._deal_id = deal
        self._tier = tier
        console.print()
        console.print(render.session_header(
            f"Session {session_number} - LIVE",
            "RevOps Finance Agent",
            task,
        ))
        console.print(render.reputation_bar(reputation, tier_for(reputation)))
        console.print()

    def on_tool_call(self, name, arguments):
        args_short = ", ".join(f"{k}={json.dumps(v)}" for k, v in list(arguments.items())[:3])
        console.print(render.step(f"{name}({args_short})", status="run"))

    def on_tool_result(self, name, result):
        if "error" in result:
            console.print(render.step(f"  {name} error", str(result["error"]), status="err"))

    def on_memory_retrieved(self, memories):
        if memories:
            for m in memories:
                content = m.get("content", "")[:100]
                console.print(render.step("  memory recalled", content, status="ok"))
        else:
            console.print(render.step("  retrieve_context", "no prior memories - cold start", status="warn"))

    def on_agent_response(self, text):
        console.print()
        console.print(render.step("Agent analysis complete", status="ok"))
        # Try to extract and render the diff table from agent JSON output
        fields = _parse_fields_from_output(text)
        if fields:
            console.print()
            console.print(render.diff_table(fields))
        console.print()

    def on_approval_needed(self, approval):
        link = approval.get("approval_link", "")
        route = approval.get("route_to", "unknown")
        console.print()
        console.print(render.routing_panel(
            f"Routed for {route.upper()} approval",
            route,
            approval.get("summary", ""),
        ))
        if link:
            console.print(render.approval_request_panel(route, link))
            if self._wait:
                approval_id = approval.get("approval_id", "")
                if approval_id:
                    try:
                        with console.status("[yellow]waiting for approval...[/]", spinner="dots"):
                            from notify.approve import store
                            decided = wait_for_approval(approval_id)
                        if decided.status == "approved":
                            console.print(render.step("Approved", status="ok"))
                        else:
                            console.print(render.step("Rejected", "CRM left unchanged", status="warn"))
                    except TimeoutError:
                        console.print(render.step("Approval timed out", status="err"))

    def on_graded(self, scorecard, graded_from_output):
        source = "agent output" if graded_from_output else "modeled fallback"
        console.print(render.outcome_panel(scorecard.outcome))
        console.print(f"[grey50]graded from: {source}[/]")
        if scorecard.notes:
            for note in scorecard.notes:
                console.print(f"  [grey70]- {note}[/]")

    def on_session_end(self, result):
        rep = result.get("reputation", 0)
        tier = tier_for(rep)
        # Fetch updated reputation after session completion
        from agent import revmem_client
        try:
            updated = revmem_client.get_agent(result.get("session_id", ""))
            rep = updated.get("reputation_score", rep)
            tier = tier_for(rep)
        except Exception:
            pass
        console.print()
        console.print(render.reputation_bar(rep, tier))
        console.print()


def _parse_fields_from_output(text: str) -> list[dict] | None:
    """Try to extract fields_compared from agent JSON output for the diff table."""
    import re
    # Find JSON object in the output
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    blob = fenced.group(1) if fenced else None
    if not blob:
        start = text.find("{")
        if start == -1:
            return None
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    blob = text[start:i + 1]
                    break
    if not blob:
        return None
    try:
        obj = json.loads(blob)
    except (json.JSONDecodeError, TypeError):
        return None
    fields_compared = obj.get("fields_compared")
    if not isinstance(fields_compared, list):
        return None
    result = []
    for f in fields_compared:
        if not isinstance(f, dict) or "field" not in f:
            continue
        materiality = f.get("materiality", "")
        if f.get("match") is True:
            verdict = "match"
        elif "material" in str(materiality).lower() and "immaterial" not in str(materiality).lower():
            verdict = "material"
        elif "immaterial" in str(materiality).lower():
            verdict = "immaterial"
        else:
            verdict = "match" if f.get("match") else "material"
        result.append({
            "field": f["field"],
            "contract": str(f.get("contract_value", "")),
            "crm": str(f.get("crm_value", "")),
            "verdict": verdict,
        })
    return result if result else None


def run_live(session_number: int, wait: bool = True) -> dict:
    from agent.runner import run_session
    listener = RichListener(wait_for_approvals=wait)
    return run_session(session_number, listener=listener)


# --- Entry point --------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="RevMem agent-working CLI.")
    parser.add_argument("--live", action="store_true", help="real Antigravity agent with Rich rendering (requires GEMINI_API_KEY)")
    parser.add_argument("--session", default=None, help="session to run: s1/s3 (scaffold) or 1/2/3 (live)")
    parser.add_argument("--no-wait", action="store_true", help="skip approval polling")
    args = parser.parse_args()

    if args.live:
        session_num = int(args.session) if args.session else 3
        if session_num not in (1, 2, 3):
            parser.error("--live sessions: 1, 2, or 3")
        run_live(session_num, wait=not args.no_wait)
    else:
        session_name = args.session or "s3"
        if session_name not in SCAFFOLD_SCENARIOS:
            parser.error(f"scaffold sessions: {', '.join(sorted(SCAFFOLD_SCENARIOS))}")
        run_scaffold(session_name, wait=not args.no_wait)


if __name__ == "__main__":
    main()
