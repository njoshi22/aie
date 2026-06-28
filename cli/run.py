"""RevMem agent-working CLI - the live terminal transcript (the demo's hero).

Two modes:
  --live            Real Antigravity agent with Rich rendering (requires GEMINI_API_KEY)
  --session s1      Scaffold replay with mock data (no API key needed)

Run:
    uv run python -m cli.run --live                # single session (default: 3)
    uv run python -m cli.run --live --all          # all 3 sessions, env-ID threaded
    uv run python -m cli.run --live --runs 10      # repeat 10x, show improvement curve
    uv run python -m cli.run --live --session 1    # specific session
    uv run python -m cli.run                       # scaffold S3 with live approval
    uv run python -m cli.run --session s1          # scaffold S1 cold start

For the live approval gate, also run the RevMem API:
    uv run uvicorn api.main:app --port 8000
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
import time
from typing import Any, NotRequired, TypedDict, cast

from dotenv import load_dotenv
from rich.console import Console

from cli import render
from evals.scorecard import summarize_sessions

load_dotenv()

console = Console()
LIVE_AGENT_NAME = "RevOps Finance Agent"


def _print_learning_scorecard(results: list[dict]) -> None:
    """Render the measured continual-learning scorecard after a multi-session run.

    No-ops on mock/empty outcomes (fewer than 2 scored sessions)."""
    panel = render.learning_scorecard(summarize_sessions(results))
    if panel is not None:
        console.print(panel)
        console.print()
JsonObject = dict[str, Any]


class DiffField(TypedDict):
    field: str
    contract: str
    crm: str
    verdict: str


class ScaffoldScenario(TypedDict, total=False):
    session_name: str
    deal_id: str
    task: str
    fields: list[DiffField]
    rep_before: float
    rep_after: float
    tier: str
    memory: str | None
    needs_approval: bool
    outcome: dict[str, object]
    discrepancy: NotRequired[str]
    recommended_fix: NotRequired[str]
    amount_usd: NotRequired[float]
    approver_role: NotRequired[str]
    approver_email: NotRequired[str]

# --- Mock scenario data (scaffold mode) --------------------------------------

ACME_FIELDS: list[DiffField] = [
    {"field": "Seats", "contract": "1,000", "crm": "1,000", "verdict": "match"},
    {"field": "TCV", "contract": "$450,000", "crm": "$450,000", "verdict": "match"},
    {"field": "Annual schedule", "contract": "$100k / $150k / $200k", "crm": "$150k / $150k / $150k", "verdict": "material"},
    {"field": "Discount", "contract": "10%", "crm": "10%", "verdict": "match"},
    {"field": "Y1 monthly invoice", "contract": "$8,333.33", "crm": "$8,333.00", "verdict": "immaterial"},
]

SCAFFOLD_SCENARIOS: dict[str, ScaffoldScenario] = {
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
        "session_name": "Session 3 - scaffold (ANALYST)",
        "deal_id": "GLOBEX-2026",
        "task": "Reconcile signed contract against Salesforce; route discrepancies.",
        "fields": [
            {"field": "Seats", "contract": "800", "crm": "800", "verdict": "match"},
            {"field": "TCV", "contract": "$360,000", "crm": "$360,000", "verdict": "match"},
            {"field": "Annual schedule", "contract": "$80k / $120k / $160k", "crm": "$120k / $120k / $120k", "verdict": "material"},
            {"field": "Discount", "contract": "25%", "crm": "20%", "verdict": "material"},
            {"field": "Y1 monthly invoice", "contract": "$6,666.67", "crm": "$6,666.00", "verdict": "immaterial"},
        ],
        "rep_before": 0.50,
        "rep_after": 0.65,
        "tier": "analyst",
        "memory": "TCV parity is insufficient for ramped deals; reconcile the annual schedule.",
        "needs_approval": True,
        "discrepancy": (
            "Year-1 revenue understated: CRM flat $120k vs ramped $80k schedule. "
            "Discount also exceeds deal-desk authority: signed 25% vs CRM 20%."
        ),
        "recommended_fix": "Set CRM annual schedule to $80k / $120k / $160k and route the over-authority discount to CFO/CCO.",
        "amount_usd": 40000.0,
        "approver_role": "controller",
        "approver_email": "controller@example.com",
        "outcome": {"material_caught": "2/2", "false_escalations": 0, "accuracy": 1.0},
    },
}


TRUE_VALUES = {"1", "true", "yes", "on"}


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in TRUE_VALUES


def _fast_mode(cli_fast: bool = False) -> bool:
    return cli_fast or _env_flag("REVMEM_CLI_FAST")


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return max(0.0, float(raw))
    except ValueError:
        return default


def _resolve_delay_scale(delay_scale: float | None = None, fast: bool = False) -> float:
    if delay_scale is not None:
        return max(0.0, delay_scale)
    if _fast_mode(fast):
        return 0.0
    return _float_env("REVMEM_DEMO_DELAY_SCALE", 1.0)


def _resolve_approval_timeout(timeout: float | None = None) -> float:
    if timeout is not None:
        return max(0.0, timeout)
    return _float_env("REVMEM_APPROVAL_TIMEOUT", 300.0)


def _resolve_approval_interval(interval: float | None = None) -> float:
    value = max(0.0, interval) if interval is not None else _float_env("REVMEM_APPROVAL_INTERVAL", 2.0)
    return max(0.01, value)


def _approval_wait_enabled(no_wait: bool, fast: bool) -> bool:
    return not no_wait and not _fast_mode(fast)


def live_runtime_error(stub_mode: bool, base_url: str, allow_stub_live: bool) -> str | None:
    if stub_mode and not allow_stub_live:
        return (
            "--live requires REVMEM_BASE_URL pointing at the RevMem API. "
            "Start `uv run uvicorn api.main:app --port 8000` and set "
            "`REVMEM_BASE_URL=http://127.0.0.1:8000`, or pass "
            "`--allow-stub-live` for an explicit offline smoke run."
        )
    if not stub_mode and not base_url:
        return "REVMEM_BASE_URL is empty even though stub mode is disabled."
    return None


def _fresh_agent_name() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"{LIVE_AGENT_NAME} demo {stamp}-{os.getpid()}"


def _beat(seconds: float = 0.6, delay_scale: float | None = None, fast: bool = False) -> None:
    scaled = seconds * _resolve_delay_scale(delay_scale, fast)
    if scaled > 0:
        time.sleep(scaled)


def tier_for(score: float) -> str:
    return "observer" if score < 0.3 else "analyst" if score < 0.6 else "autonomous"


def wait_for_revmem_approval(approval_request_id: str, timeout: float = 300.0, interval: float = 2.0) -> JsonObject:
    from agent import revmem_client

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = revmem_client.get_approval_status(approval_request_id)
        if status.get("status") != "pending":
            return status
        time.sleep(interval)
    raise TimeoutError(f"approval request {approval_request_id} not decided within {timeout:.0f}s")


def approval_link_location_detail() -> str:
    from agent import revmem_client

    if revmem_client.STUB_MODE:
        return "Offline stub mode: no clickable approval link is created. Set REVMEM_BASE_URL and run api.main for real approval links."
    return "Human approval link is printed by the RevMem API server logs."


def approval_source_label(source: str) -> str:
    if source == "model":
        return "model tool call"
    return "unknown source"


# --- Scaffold mode ------------------------------------------------------------

def run_scaffold(
    name: str,
    wait: bool = True,
    delay_scale: float | None = None,
    approval_timeout: float | None = None,
    approval_interval: float | None = None,
) -> None:
    sc = SCAFFOLD_SCENARIOS[name]
    console.print()
    console.print(render.session_header(sc["session_name"], "RevOps Finance Agent", sc["task"]))
    console.print(render.reputation_bar(sc["rep_before"], tier_for(sc["rep_before"])))
    console.print()

    console.print(render.step(f"get_contract({sc['deal_id']})  +  get_crm_record(...)", status="ok"))
    _beat(delay_scale=delay_scale)

    if sc["memory"]:
        console.print(render.step("retrieve_context(...)", f'recalled: "{sc["memory"]}"', status="ok"))
    else:
        console.print(render.step("retrieve_context(...)", "no prior memories - cold start", status="warn"))
    _beat(delay_scale=delay_scale)

    console.print()
    console.print(render.diff_table(cast(list[dict[str, str]], sc["fields"])))
    console.print()

    for f in sc["fields"]:
        if f["verdict"] == "immaterial":
            if sc["tier"] == "observer":
                console.print(render.step(f"{f['field']}: rounding artifact", "ESCALATED (cold agent over-flags)", status="warn"))
            else:
                console.print(render.step(f"{f['field']}: rounding artifact", "dismissed as immaterial", status="ok"))
            _beat(0.4, delay_scale=delay_scale)
        elif f["verdict"] == "material":
            if sc["tier"] == "observer":
                console.print(render.step(f"{f['field']}: ramp restructuring", "MISSED (no learned context)", status="err"))
            else:
                console.print(render.step(f"{f['field']}: ramp restructuring", "caught - material, routing for approval", status="ok"))
            _beat(0.4, delay_scale=delay_scale)

    if not sc["needs_approval"]:
        console.print()
        console.print(render.outcome_panel(sc["outcome"]))
        console.print(render.reputation_bar(sc["rep_after"], tier_for(sc["rep_after"])))
        console.print("\n[grey70]Reviewer correction on this outcome creates the one experiential memory.[/]\n")
        return

    console.print()
    approver_role = sc.get("approver_role", "cfo")
    approver_label = approver_role.replace("_", " + ").upper()
    console.print(render.routing_panel(sc["discrepancy"], approver_label, sc["recommended_fix"]))

    from agent import revmem_client

    agent_state = revmem_client.ensure_agent(LIVE_AGENT_NAME)
    approval = revmem_client.route_for_approval(
        agent_id=str(agent_state["id"]),
        deal_id=sc["deal_id"],
        amount_usd=float(sc.get("amount_usd", 0)),
        change_type="schedule_change",
        summary=sc["discrepancy"],
        recommended_fix=sc["recommended_fix"],
    )
    approval_request_id = str(approval.get("approval_request_id", ""))
    link = str(approval.get("approval_link", ""))
    route = str(approval.get("route_to", sc["approver_email"]))
    if link:
        console.print(render.approval_request_panel(route, link))
    else:
        console.print(render.step("Approval requested", approval_link_location_detail(), status="warn"))

    if not wait:
        detail = f"approval_request_id={approval_request_id}" if approval_request_id else "approval_request_id unavailable"
        console.print(f"\n[grey70]--no-wait: {detail}. This run will not resume.[/]\n")
        return

    if not approval_request_id:
        console.print("\n[red]Approval request did not return an approval_request_id - leaving CRM unchanged.[/]\n")
        return

    try:
        with console.status(f"[yellow]waiting for {approver_label} approval...[/]", spinner="dots"):
            decided = wait_for_revmem_approval(
                approval_request_id,
                timeout=_resolve_approval_timeout(approval_timeout),
                interval=_resolve_approval_interval(approval_interval),
            )
    except TimeoutError:
        console.print("\n[red]Approval timed out - leaving CRM unchanged.[/]\n")
        return

    if decided.get("status") == "approved":
        console.print(render.step(f"{approver_label} approved", status="ok"))
        _beat(delay_scale=delay_scale)
        console.print(render.step(f"write_crm({sc['deal_id']}, corrected_fields)", "ANALYST permission - executed", status="ok"))
        console.print()
        console.print(render.outcome_panel(sc["outcome"]))
        console.print(render.reputation_bar(sc["rep_after"], tier_for(sc["rep_after"])))
        console.print("\n[green]Reconciled. Reputation rises -> next deal could auto-reconcile unattended.[/]\n")
    else:
        console.print(render.step(f"{approver_label} rejected", "CRM left unchanged", status="warn"))


# --- Live mode (real Antigravity agent + Rich rendering) ----------------------

class RichListener:
    """Renders real agent events through the Rich CLI panels."""

    def __init__(
        self,
        wait_for_approvals: bool = True,
        approval_timeout: float | None = None,
        approval_interval: float | None = None,
    ):
        self._wait = wait_for_approvals
        self._approval_timeout = approval_timeout
        self._approval_interval = approval_interval
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
        fields = _parse_fields_from_output(text)
        if fields:
            console.print()
            console.print(render.diff_table(fields))
        console.print()

    def on_approval_needed(self, approval):
        link = approval.get("approval_link", "")
        route = approval.get("route_to", "unknown")
        source = approval_source_label(str(approval.get("source", "")))
        summary = str(approval.get("summary", ""))
        detail = summary if summary else f"Approval requested by {source}"
        console.print()
        console.print(render.routing_panel(
            f"Routed for {route.upper()} approval",
            route,
            f"{detail} ({source})",
        ))
        if link:
            console.print(render.approval_request_panel(route, link))
        else:
            console.print(
                render.step(
                    "Approval created",
                    "human approval link is held by the RevMem API server log",
                    status="warn",
                )
            )
        if self._wait:
            approval_request_id = str(approval.get("approval_request_id", ""))
            if approval_request_id:
                try:
                    with console.status("[yellow]waiting for approval...[/]", spinner="dots"):
                        decided = wait_for_revmem_approval(
                            approval_request_id,
                            timeout=_resolve_approval_timeout(self._approval_timeout),
                            interval=_resolve_approval_interval(self._approval_interval),
                        )
                    if decided.get("status") == "approved":
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
        from agent import revmem_client
        try:
            updated = revmem_client.get_agent(result.get("agent_id", ""))
            rep = float(updated.get("reputation_score", rep))
            tier = str(updated.get("permission_tier", tier_for(rep)))
        except Exception:
            pass
        console.print()
        console.print(render.reputation_bar(rep, tier))
        console.print()

    def on_agent_api_start(self, label):
        console.print(render.step(f"hosted agent API: {label}", "waiting for model response...", status="run"))

    def on_agent_api_end(self, label, elapsed_s):
        console.print(render.step(f"hosted agent API: {label}", f"{elapsed_s:.1f}s", status="ok"))

    def on_tool_timing(self, name, elapsed_s):
        if name in {"read_file", "list_files"} and elapsed_s < 0.1:
            return
        console.print(render.step(f"{name} completed", f"{elapsed_s:.1f}s", status="ok"))


def _parse_fields_from_output(text: str) -> list[dict] | None:
    """Try to extract fields_compared from agent JSON output for the diff table."""
    import re
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


def run_live(
    session_number: int,
    wait: bool = True,
    env_id: str | None = None,
    prev_interaction: str | None = None,
    approval_timeout: float | None = None,
    approval_interval: float | None = None,
    agent_name: str = LIVE_AGENT_NAME,
    debug: bool = False,
) -> dict:
    from agent.runner import run_session
    listener = RichListener(
        wait_for_approvals=wait,
        approval_timeout=approval_timeout,
        approval_interval=approval_interval,
    )
    return run_session(
        session_number,
        env_id=env_id,
        prev_interaction_id=prev_interaction,
        listener=listener,
        agent_name=agent_name,
        debug=debug,
    )


def run_live_all(
    wait: bool = True,
    approval_timeout: float | None = None,
    approval_interval: float | None = None,
    pause_between: bool = True,
    agent_name: str = LIVE_AGENT_NAME,
    debug: bool = False,
) -> list[dict]:
    """Run sessions 1->2->3 with env-ID threading -- the full demo narrative."""
    from agent.scenarios import SCENARIOS

    console.print()
    console.print(render.divider("RevMem Demo — 3 sessions, continual learning"))

    results = []
    env_id = None
    prev_interaction = None
    prev_deal = None

    for session_num in [1, 2, 3]:
        if session_num > 1 and pause_between:
            console.print(render.divider(f"Session {session_num}"))
            console.input("[grey50]Press Enter to continue...[/]")

        current_deal = SCENARIOS[session_num]["deal"]
        if current_deal != prev_deal:
            env_id = None
            prev_interaction = None

        result = run_live(
            session_num,
            wait=wait,
            env_id=env_id,
            prev_interaction=prev_interaction,
            approval_timeout=approval_timeout,
            approval_interval=approval_interval,
            agent_name=agent_name,
            debug=debug,
        )
        results.append(result)

        prev_deal = current_deal
        env_id = result.get("environment_id")
        prev_interaction = result.get("interaction_id")

    console.print()
    console.print(render.run_summary_table(results))
    console.print()
    _print_learning_scorecard(results)
    return results


def run_live_repeat(
    runs: int,
    wait: bool = True,
    approval_timeout: float | None = None,
    approval_interval: float | None = None,
    agent_name: str = LIVE_AGENT_NAME,
    debug: bool = False,
) -> list[dict]:
    """Seed once with S1/S2, then repeat S3 to show self-improvement.

    The intentional cold-start failure is setup, not a repeated trial. The
    counted runs are post-seed generalization attempts whose reputation and
    memories accumulate on the same agent.
    """
    from agent.scenarios import SCENARIOS

    console.print()
    console.print(render.divider(f"RevMem Self-Improvement — {runs} runs"))

    results = []
    env_id = None
    prev_interaction = None
    prev_deal = None
    sequence: list[tuple[int, str]] = [(1, "Seed 1/2"), (2, "Seed 2/2")]
    sequence.extend((3, f"Run {i}/{runs}") for i in range(1, runs + 1))

    for index, (session_num, label) in enumerate(sequence, start=1):
        console.print(render.divider(label))

        current_deal = SCENARIOS[session_num]["deal"]
        if current_deal != prev_deal:
            env_id = None
            prev_interaction = None

        result = run_live(
            session_num,
            wait=wait,
            env_id=env_id,
            prev_interaction=prev_interaction,
            approval_timeout=approval_timeout,
            approval_interval=approval_interval,
            agent_name=agent_name,
            debug=debug,
        )
        result["run"] = label if session_num != 3 else index - 2
        results.append(result)

        prev_deal = current_deal
        env_id = result.get("environment_id")
        prev_interaction = result.get("interaction_id")

    console.print()
    console.print(render.run_summary_table(results))
    console.print()
    _print_learning_scorecard(results)
    return results


# --- Continuous mode (one interaction chain with human feedback) ---------------

def run_continuous(
    wait: bool = True,
    approval_timeout: float | None = None,
    approval_interval: float | None = None,
    agent_name: str = LIVE_AGENT_NAME,
    debug: bool = False,
) -> list[dict]:
    """Run a continuous interaction chain: Acme → human feedback → Globex.

    All interactions share one environment_id. The human types real corrections
    between deals, and the agent autonomously calls store_memory.
    """
    from agent.runner import run_session, send_feedback

    console.print()
    console.print(render.divider("RevMem Continuous Demo — live human correction"))

    listener = RichListener(
        wait_for_approvals=wait,
        approval_timeout=approval_timeout,
        approval_interval=approval_interval,
    )

    # --- Step 1: Run Acme (session 1) — agent has no memories, may make judgment errors
    console.print(render.divider("Step 1: Acme Corp — no prior memories"))
    result_s1 = run_session(
        session_number=1,
        listener=listener,
        agent_name=agent_name,
        debug=debug,
    )

    env_id = result_s1["environment_id"]
    prev_interaction = result_s1["interaction_id"]
    agent_id = result_s1["agent_id"]
    session_id = result_s1["session_id"]

    # --- Step 2: Collect human feedback
    console.print(render.divider("Step 2: Human reviewer feedback"))
    console.print()
    console.print(
        render.step(
            "Review the agent's analysis above",
            "What did it get wrong? Type your correction below.",
            status="warn",
        )
    )
    console.print()
    feedback = console.input("[bold yellow]Your feedback:[/] ")
    if not feedback.strip():
        feedback = (
            "The $0.33 monthly invoice difference is a rounding artifact — "
            "per DOA-001, differences under $1 should be auto-dismissed, not escalated. "
            "Also, the annual schedule mismatch is a schedule_change and should be "
            "routed to the Controller per DOA-003, not the CFO."
        )
        console.print(f"[grey50](using default feedback: {feedback})[/]")

    console.print()
    console.print(render.step("Sending feedback to agent...", status="run"))

    feedback_result = send_feedback(
        feedback_text=feedback,
        env_id=env_id,
        prev_interaction_id=prev_interaction,
        agent_id=agent_id,
        session_id=session_id,
        listener=listener,
        debug=debug,
    )

    if feedback_result.get("memory_stored"):
        console.print(render.step("Agent stored lesson via store_memory", status="ok"))
    else:
        console.print(render.step("Agent did NOT call store_memory", "lesson may not persist", status="warn"))

    prev_interaction = feedback_result["interaction_id"]
    env_id = feedback_result["environment_id"]

    # --- Step 3: Run Globex (session 3) — agent should retrieve lesson and generalize
    console.print(render.divider("Step 3: Globex Inc — testing generalization"))
    result_s3 = run_session(
        session_number=3,
        env_id=env_id,
        prev_interaction_id=prev_interaction,
        listener=listener,
        agent_name=agent_name,
        debug=debug,
    )

    # --- Summary
    results = [result_s1, result_s3]
    console.print()
    console.print(render.run_summary_table(results))
    console.print()
    _print_learning_scorecard(results)
    return results


# --- Entry point --------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="RevMem agent-working CLI.")
    parser.add_argument("--live", action="store_true", help="real Antigravity agent with Rich rendering (requires GEMINI_API_KEY)")
    parser.add_argument("--continuous", action="store_true", help="continuous interaction chain with live human feedback (requires GEMINI_API_KEY)")
    parser.add_argument("--all", action="store_true", help="run all 3 sessions (1->2->3) with env-ID threading")
    parser.add_argument("--runs", type=int, default=None, metavar="N", help="seed once, then run N learned trials")
    parser.add_argument("--session", default=None, help="session to run: s1/s3 (scaffold) or 1/2/3 (live)")
    parser.add_argument("--no-wait", action="store_true", help="skip approval polling")
    parser.add_argument("--fast", action="store_true", help="skip demo pacing and approval polling for local integration checks")
    parser.add_argument("--approval-timeout", type=float, default=None, help="seconds to wait for approval before timing out")
    parser.add_argument("--approval-interval", type=float, default=None, help="seconds between approval status polls")
    parser.add_argument("--allow-stub-live", action="store_true", help="allow --live to use offline RevMem stubs; diagnostic only")
    parser.add_argument("--agent-name", default=None, help="RevMem live agent name to get or create")
    parser.add_argument("--reuse-agent", action="store_true", help="reuse the persisted live demo agent for --all/--runs")
    parser.add_argument("--debug-agent", action="store_true", help="print live Interactions API step debugging")
    args = parser.parse_args()
    fast = _fast_mode(args.fast)
    wait = _approval_wait_enabled(args.no_wait, fast)
    delay_scale = _resolve_delay_scale(fast=fast)
    agent_name = args.agent_name
    if agent_name is None:
        agent_name = LIVE_AGENT_NAME if args.reuse_agent or not (args.all or args.runs or args.continuous) else _fresh_agent_name()

    if args.continuous:
        from agent import revmem_client

        error = live_runtime_error(
            stub_mode=revmem_client.STUB_MODE,
            base_url=revmem_client.REVMEM_BASE_URL,
            allow_stub_live=args.allow_stub_live,
        )
        if error:
            parser.error(error)

        run_continuous(
            wait=wait,
            approval_timeout=args.approval_timeout,
            approval_interval=args.approval_interval,
            agent_name=agent_name,
            debug=args.debug_agent,
        )
    elif args.live:
        from agent import revmem_client

        error = live_runtime_error(
            stub_mode=revmem_client.STUB_MODE,
            base_url=revmem_client.REVMEM_BASE_URL,
            allow_stub_live=args.allow_stub_live,
        )
        if error:
            parser.error(error)

        if args.runs is not None:
            if args.runs < 1:
                parser.error("--runs must be >= 1")
            run_live_repeat(
                args.runs,
                wait=wait,
                approval_timeout=args.approval_timeout,
                approval_interval=args.approval_interval,
                agent_name=agent_name,
                debug=args.debug_agent,
            )
        elif args.all:
            run_live_all(
                wait=wait,
                approval_timeout=args.approval_timeout,
                approval_interval=args.approval_interval,
                pause_between=not fast,
                agent_name=agent_name,
                debug=args.debug_agent,
            )
        else:
            session_num = int(args.session) if args.session else 3
            if session_num not in (1, 2, 3):
                parser.error("--live sessions: 1, 2, or 3")
            run_live(
                session_num,
                wait=wait,
                approval_timeout=args.approval_timeout,
                approval_interval=args.approval_interval,
                agent_name=agent_name,
                debug=args.debug_agent,
            )
    else:
        if args.all:
            for session_name in sorted(SCAFFOLD_SCENARIOS):
                run_scaffold(
                    session_name,
                    wait=wait,
                    delay_scale=delay_scale,
                    approval_timeout=args.approval_timeout,
                    approval_interval=args.approval_interval,
                )
        else:
            session_name = args.session or "s3"
            if session_name not in SCAFFOLD_SCENARIOS:
                parser.error(f"scaffold sessions: {', '.join(sorted(SCAFFOLD_SCENARIOS))}")
            run_scaffold(
                session_name,
                wait=wait,
                delay_scale=delay_scale,
                approval_timeout=args.approval_timeout,
                approval_interval=args.approval_interval,
            )


if __name__ == "__main__":
    main()
