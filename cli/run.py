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

    def on_agent_delta(self, text: str) -> None:
        pass

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

    def on_production_locked(self, payload):
        console.print()
        console.print(render.prod_lock_panel(
            float(payload.get("reputation_score", 0.0)),
            float(payload.get("floor", 0.3)),
            str(payload.get("reason", "")),
        ))

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
    # The routed-approval wait is handled after the session so it works in MCP mode,
    # where the agent's tool calls run server-side and never reach the in-loop listener.
    listener = RichListener(
        wait_for_approvals=False,
        approval_timeout=approval_timeout,
        approval_interval=approval_interval,
    )
    result = run_session(
        session_number,
        env_id=env_id,
        prev_interaction_id=prev_interaction,
        listener=listener,
        agent_name=agent_name,
        debug=debug,
    )
    _print_tier_transition(result)
    _show_routed_approvals(result, wait=wait,
                           approval_timeout=approval_timeout, approval_interval=approval_interval)
    return result


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

def _print_tier_transition(result: dict) -> None:
    """Show the reputation/tier change after a session — the 'earns autonomy' beat."""
    start_t, end_t = result.get("starting_tier"), result.get("tier")
    start_r, end_r = result.get("starting_reputation"), result.get("reputation")
    if start_t != end_t:
        console.print(render.step(
            f"Reputation {start_r} → {end_r} · tier {str(start_t).upper()} → {str(end_t).upper()}",
            "policy widened permissions — no human re-explaining", status="ok"))
    else:
        console.print(render.step(f"Reputation {start_r} → {end_r} · tier {str(end_t).upper()}", status="run"))


def _show_routed_approvals(result: dict, wait: bool,
                           approval_timeout: float | None, approval_interval: float | None) -> None:
    """Show the approval(s) the agent routed this session, optionally blocking for sign-off.

    Transport-agnostic: in MCP mode the runner never sees the agent's server-side tool
    calls, so the routed approvals are read from the session result (reconstructed there).
    """
    from agent import revmem_client

    routed = [a for a in result.get("approvals_routed", []) if a.get("approval_request_id")]
    if not routed:
        console.print(render.step("No correction routed for approval this session", status="warn"))
        return
    for appr in routed:
        request_id = str(appr["approval_request_id"])
        role = str(appr.get("route_to") or "approver")
        base = revmem_client.REVMEM_BASE_URL
        inbox = f"{base}/approval-inbox/{role}" if base else "(held in the RevMem server log)"
        console.print(render.approval_request_panel(role, inbox))
        if not wait:
            continue
        with console.status(f"[yellow]waiting for {role.upper()} approval…[/]", spinner="dots"):
            try:
                decided = wait_for_revmem_approval(
                    request_id,
                    timeout=_resolve_approval_timeout(approval_timeout),
                    interval=_resolve_approval_interval(approval_interval),
                )
            except TimeoutError:
                console.print(render.step("Approval timed out", "demo continues unapproved", status="warn"))
                continue
        status = str(decided.get("status", ""))
        if status == "approved":
            console.print(render.step(f"{role.upper()} approved — correction cleared through the gate", status="ok"))
        else:
            console.print(render.step(f"Approval {status}", status="warn"))


def run_continuous(
    wait: bool = True,
    approval_timeout: float | None = None,
    approval_interval: float | None = None,
    agent_name: str = LIVE_AGENT_NAME,
    debug: bool = False,
) -> list[dict]:
    """Continuous chain following the demo script: Acme cold start → human
    correction → Acme again (agent applies the lesson and routes a correction
    that waits for human approval). All interactions share one environment_id.
    """
    from agent.runner import run_session, send_feedback

    console.print()
    console.print(render.divider("RevMem Continuous Demo — cold start → correction → earned autonomy"))

    # Session 1's routing is shown but not blocked on; session 2 waits for approval.
    listener = RichListener(
        wait_for_approvals=False,
        approval_timeout=approval_timeout,
        approval_interval=approval_interval,
    )

    # --- Step 1: Run Acme (session 1) — cold start, observer/read-only, routes through the gate
    console.print(render.divider("Step 1: Acme Corp — cold start, no memories"))
    result_s1 = run_session(
        session_number=1,
        listener=listener,
        agent_name=agent_name,
        debug=debug,
    )
    _print_tier_transition(result_s1)
    _show_routed_approvals(result_s1, wait=False,
                           approval_timeout=approval_timeout, approval_interval=approval_interval)

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

    # --- Step 3: Run Acme again (session 2) — agent retrieves the lesson, catches it on its own
    console.print(render.divider("Step 3: Acme Corp again — agent applies the lesson"))
    result_s2 = run_session(
        session_number=2,
        env_id=env_id,
        prev_interaction_id=prev_interaction,
        listener=listener,
        agent_name=agent_name,
        debug=debug,
    )
    _print_tier_transition(result_s2)

    # --- Step 4: human approval gate — the agent routed a correction; wait for sign-off
    console.print(render.divider("Step 4: Human approval gate"))
    _show_routed_approvals(result_s2, wait=wait,
                           approval_timeout=approval_timeout, approval_interval=approval_interval)

    # --- Summary
    results = [result_s1, result_s2]
    console.print()
    console.print(render.run_summary_table(results))
    console.print()
    _print_learning_scorecard(results)
    return results


# --- Self-heal mode (governed recursive self-improvement) ---------------------

# A representative correction the agent would write once it has recovered.
_GLOBEX_CORRECTION = {"annual_schedule_usd": [80000, 120000, 160000]}
_GLOBEX_DISCREPANCY = {
    "deal_id": "globex", "field": "annual_schedule_usd", "change_type": "schedule_change",
    "contract_value": [80000, 120000, 160000], "crm_value": [120000, 120000, 120000],
    "diff_usd": 40000.0,
}


def _self_heal_db():
    from core import database
    return database.get_connection(os.getenv("REVMEM_DB", str(database.DB_PATH)))


def _seed_reputation_history(agent_id: str, accuracies: list[float]) -> None:
    """Drive reputation to a known starting point via real complete_session calls."""
    from agent import revmem_client
    for acc in accuracies:
        s = revmem_client.start_session(agent_id, "seed reconciliation")
        revmem_client.complete_session(str(s["id"]), {"accuracy": acc})


def _attempt_prod_write(agent_id: str) -> dict:
    """Attempt a CRM write; returns the service result (lock dict or approval payload)."""
    from agent import revmem_client
    return revmem_client.write_crm(
        agent_id=agent_id, deal_id="globex",
        fields=_GLOBEX_CORRECTION, discrepancy=_GLOBEX_DISCREPANCY,
    )


def run_self_heal(
    wait: bool = True,
    approval_timeout: float | None = None,
    approval_interval: float | None = None,
    agent_name: str = LIVE_AGENT_NAME,
    debug: bool = False,
) -> list[dict]:
    """Governed recursive self-improvement: bad run -> reputation tanks -> production
    LOCKED -> diagnose -> agent rewrites its own skill -> re-eval -> reputation
    recovers -> production RESTORED. The hero demo."""
    from agent import revmem_client
    from agent.runner import run_session
    from core import optimizer, reputation
    from core.demo_skills import WEAK_SKILL_V0
    from data.seed import seed_skill_v0

    floor = reputation.PRODUCTION_FLOOR
    listener = RichListener(
        wait_for_approvals=wait,
        approval_timeout=approval_timeout,
        approval_interval=approval_interval,
    )

    console.print()
    console.print(render.divider("RevMem: Governed Recursive Self-Improvement"))

    # --- Phase 1: seed a shaky-but-trusted agent (rep ~0.33, just above the floor)
    agent = revmem_client.ensure_agent(agent_name)
    agent_id = str(agent["id"])
    conn = _self_heal_db()
    seed_skill_v0(conn, agent_id)                        # active skill = weak v0
    _seed_reputation_history(agent_id, [1.0, 0.0, 0.0])  # -> reputation ~0.33, ANALYST
    agent = revmem_client.get_agent(agent_id)
    rep = float(agent["reputation_score"])
    console.print(render.step("Agent has production write access, but its recent record is shaky.", status="warn"))
    console.print(render.reputation_bar(rep, agent["permission_tier"]))

    # --- Phase 2: a bad run on the regressed skill tanks reputation below the floor
    console.print(render.divider("Bad run - regressed skill"))
    result_bad = run_session(
        session_number=3, env_id=None, skill_override=WEAK_SKILL_V0,
        force_step="globex_regressed", listener=listener, agent_name=agent_name, debug=debug,
    )

    # --- Phase 3: production write is now locked, server-side
    console.print(render.divider("Production write attempt"))
    lock = _attempt_prod_write(agent_id)
    if lock.get("production_locked"):
        console.print(render.prod_lock_panel(
            float(lock.get("reputation_score", result_bad.get("reputation", 0.0))),
            float(lock.get("floor", floor)), str(lock.get("reason", "")),
        ))
    else:
        console.print(render.step("Expected a production lock but the write was not blocked.", status="err"))

    # --- Phase 4: diagnose + rewrite the skill (genuinely live, canned fallback)
    console.print(render.divider("Self-improvement loop"))
    console.print(render.step("Diagnosing failure and rewriting the skill...", status="run"))
    opt = optimizer.optimize_skill(conn, agent_id)
    console.print(render.prompt_diff_panel(opt.base_skill, opt.new_skill))
    mode = "canned fallback" if opt.fallback else "live Gemini rewrite"
    console.print(render.step(
        f"Skill re-scored: {opt.base_score:.2f} -> {opt.new_score:.2f}  ({mode})",
        opt.rationale, status="ok",
    ))
    console.print(render.reputation_bar(opt.reputation_after or 0.0, tier_for(opt.reputation_after or 0.0)))

    # --- Phase 5: production access restored; recovery run uses the rewritten skill
    if (opt.reputation_after or 0.0) >= floor:
        console.print(render.prod_unlock_panel(opt.reputation_after or 0.0, floor))
    console.print(render.divider("Recovery run - self-optimized skill"))
    result_good = run_session(
        session_number=3, env_id=None, skill_override=opt.new_skill,
        force_step="globex_learned", listener=listener, agent_name=agent_name, debug=debug,
    )

    # --- Summary
    results = [result_bad, result_good]
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
    parser.add_argument("--self-heal", dest="self_heal", action="store_true", help="governed recursive self-improvement: bad run -> production lock -> skill rewrite -> recovery (requires GEMINI_API_KEY)")
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
    parser.add_argument("--stream", action="store_true", help="stream hosted-agent events live instead of background polling")
    args = parser.parse_args()
    if args.stream:
        os.environ["REVMEM_STREAM"] = "1"
    fast = _fast_mode(args.fast)
    wait = _approval_wait_enabled(args.no_wait, fast)
    delay_scale = _resolve_delay_scale(fast=fast)
    agent_name = args.agent_name
    if agent_name is None:
        agent_name = LIVE_AGENT_NAME if args.reuse_agent or not (args.all or args.runs or args.continuous or args.self_heal) else _fresh_agent_name()

    if args.self_heal:
        from agent import revmem_client

        error = live_runtime_error(
            stub_mode=revmem_client.STUB_MODE,
            base_url=revmem_client.REVMEM_BASE_URL,
            allow_stub_live=args.allow_stub_live,
        )
        if error:
            parser.error(error)

        run_self_heal(
            wait=wait,
            approval_timeout=args.approval_timeout,
            approval_interval=args.approval_interval,
            agent_name=agent_name,
            debug=args.debug_agent,
        )
    elif args.continuous:
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
