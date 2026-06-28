"""Rich renderables for the RevMem agent-working CLI.

Everything the judge sees is a terminal panel. These helpers turn RevMem state
(contract/CRM diff, reputation, routing, approval) into inline Rich objects that
``cli/run.py`` streams as the agent works. No web dashboard anywhere.
"""

from __future__ import annotations

import difflib

from rich.box import ROUNDED, SIMPLE
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# tier -> accent color, used by the reputation bar and tier labels
TIER_COLORS = {
    "observer": "yellow",
    "analyst": "cyan",
    "autonomous": "green",
}

# verdict -> (style, label) for the contract-vs-CRM diff table
VERDICT_STYLE = {
    "match": ("green", "match"),
    "immaterial": ("yellow", "immaterial"),
    "material": ("bold red", "MISMATCH - material"),
}


def session_header(session_name: str, agent_name: str, task: str) -> Panel:
    body = Text()
    body.append(f"{agent_name}\n", style="bold")
    body.append(f"{task}\n\n", style="grey70")
    body.append(session_name, style="bold blue")
    return Panel(body, box=ROUNDED, border_style="blue", padding=(1, 2))


def reputation_bar(score: float, tier: str, width: int = 24) -> Panel:
    """Inline reputation overlay: a 0..1 bar plus the earned permission tier."""
    score = max(0.0, min(1.0, score))
    filled = int(round(score * width))
    color = TIER_COLORS.get(tier.lower(), "white")
    line = Text()
    line.append("reputation  ", style="bold")
    line.append("#" * filled, style=color)
    line.append("." * (width - filled), style="grey37")
    line.append(f"  {score:.2f}", style="bold")
    line.append("   tier ", style="bold")
    line.append(tier.upper(), style=f"bold {color}")
    return Panel(line, box=SIMPLE, padding=(0, 1))


def diff_table(fields: list[dict]) -> Table:
    """fields: list of {field, contract, crm, verdict} where verdict is one of
    match | immaterial | material."""
    table = Table(
        title="Signed contract  vs  Salesforce (CRM)",
        title_style="bold",
        box=ROUNDED,
        expand=True,
    )
    table.add_column("Field")
    table.add_column("Signed contract", justify="right")
    table.add_column("Salesforce", justify="right")
    table.add_column("Verdict")
    for f in fields:
        style, label = VERDICT_STYLE.get(f["verdict"], ("white", f["verdict"]))
        table.add_row(f["field"], str(f["contract"]), str(f["crm"]), Text(label, style=style))
    return table


def step(title: str, detail: str | None = None, status: str = "run") -> Text:
    """A single agent action line. status: run | ok | warn | err."""
    icons = {
        "run": ("->", "cyan"),
        "ok": ("ok", "green"),
        "warn": ("!", "yellow"),
        "err": ("x", "red"),
    }
    icon, color = icons.get(status, ("->", "cyan"))
    text = Text()
    text.append(f"[{icon}] ", style=f"bold {color}")
    text.append(title, style="bold")
    if detail:
        text.append(f"\n     {detail}", style="grey70")
    return text


def routing_panel(discrepancy: str, approver: str, recommended_fix: str | None = None) -> Panel:
    body = Text()
    body.append("discrepancy   ", style="bold")
    body.append(f"{discrepancy}\n")
    if recommended_fix:
        body.append("recommended   ", style="bold")
        body.append(f"{recommended_fix}\n")
    body.append("route to      ", style="bold")
    body.append(approver.upper(), style="bold magenta")
    return Panel(body, title="Governance - approver routing", border_style="magenta", box=ROUNDED)


def approval_request_panel(approver_email: str, approve_url: str, waiting: bool = True) -> Panel:
    body = Text()
    body.append("approval target  ", style="bold")
    body.append(f"{approver_email}\n", style="green")
    if waiting:
        body.append("waiting for human sign-off...\n\n", style="yellow")
    else:
        body.append("approval wait disabled for this run\n\n", style="yellow")
    body.append("approve link   ", style="bold")
    body.append(approve_url, style="underline blue")
    return Panel(
        body,
        title="Human-in-the-loop approval",
        border_style="yellow",
        box=ROUNDED,
    )


def outcome_panel(outcome: dict) -> Panel:
    body = Text()
    for k, v in outcome.items():
        body.append(f"{k:<18}", style="bold")
        body.append(f"{v}\n")
    return Panel(body, title="Outcome (logged to RevMem)", border_style="grey50", box=ROUNDED)


def run_summary_table(results: list[dict]) -> Table:
    """Summary table across multiple sessions showing improvement trajectory."""
    table = Table(
        title="Self-Improvement Trajectory",
        title_style="bold",
        box=ROUNDED,
        expand=True,
    )
    table.add_column("Run", justify="right", style="bold")
    table.add_column("Deal")
    table.add_column("Tier")
    table.add_column("Reputation", justify="right")
    table.add_column("Memories", justify="right")
    table.add_column("Accuracy", justify="right")
    table.add_column("Material caught", justify="right")
    table.add_column("False esc.", justify="right")

    for r in results:
        tier = r.get("tier", "?")
        color = TIER_COLORS.get(tier.lower(), "white")
        outcome = r.get("outcome", {})
        table.add_row(
            str(r.get("session_number", r.get("run", "?"))),
            r.get("deal", "?").upper(),
            Text(tier.upper(), style=f"bold {color}"),
            f"{r.get('reputation', 0):.2f}",
            str(r.get("memories_used", 0)),
            f"{outcome.get('accuracy', 0):.1%}" if isinstance(outcome.get("accuracy"), (int, float)) else str(outcome.get("accuracy", "?")),
            str(outcome.get("material_caught", "?")),
            str(outcome.get("false_escalations", "?")),
        )
    return table


def learning_scorecard(summary: dict) -> Panel | None:
    """Measured continual-learning panel from ``evals.scorecard.summarize_sessions``.

    Returns None when fewer than 2 sessions were scored (nothing to compare), so
    callers can simply skip rendering on mock/empty runs.
    """
    points = summary.get("curve", [])
    if summary.get("n", 0) < 2:
        return None

    body = Text()
    for p in points:
        acc = p["accuracy"]
        filled = int(round(max(0.0, min(1.0, acc)) * 16))
        deal = str(p.get("deal") or "").upper()
        body.append(f"S{p['session']} {deal:<7} ", style="bold")
        body.append("#" * filled, style="green")
        body.append("." * (16 - filled), style="grey37")
        recall = ""
        if p.get("material_total") and p.get("material_caught") is not None:
            recall = f"  recall {int(p['material_caught'])}/{int(p['material_total'])}"
        fe = p.get("false_escalations")
        body.append(f"  acc {acc:.2f}{recall}  false-esc {fe if fe is not None else '?'}\n")

    deltas = summary.get("deltas", {})
    first, last = summary["first"], summary["last"]
    body.append("\n")

    def _delta_line(label: str, a, b, value, good_down: bool = False) -> None:
        body.append(f"{label:<18}", style="bold")
        body.append(f"{a} -> {b}")
        if value is None or value == 0:
            body.append("\n", style="grey50")
            return
        good = (value < 0) if good_down else (value > 0)
        sign = "+" if value > 0 else ""
        body.append(f"   ({sign}{value})\n", style="green" if good else "red")

    _delta_line("accuracy", f"{first['accuracy']:.2f}", f"{last['accuracy']:.2f}", deltas.get("accuracy"))
    _delta_line(
        "false escalations",
        first.get("false_escalations", "?"),
        last.get("false_escalations", "?"),
        deltas.get("false_escalations"),
        good_down=True,
    )
    if first.get("material_recall") is not None and last.get("material_recall") is not None:
        _delta_line(
            "material recall",
            f"{first['material_recall']:.2f}",
            f"{last['material_recall']:.2f}",
            deltas.get("material_recall"),
        )

    improved = summary.get("improved")
    title = "Continual learning - measured improvement" if improved else "Continual learning - scorecard"
    return Panel(body, title=title, border_style="green" if improved else "grey50", box=ROUNDED)


def prod_lock_panel(reputation: float, floor: float, reason: str = "") -> Panel:
    """Shown when write_crm trips the reputation circuit breaker (server-enforced)."""
    body = Text()
    body.append("  PRODUCTION ACCESS REVOKED\n\n", style="bold red")
    body.append("write_crm   ", style="bold")
    body.append("DENIED by governance\n", style="bold red")
    body.append("reputation  ", style="bold")
    body.append(f"{reputation:.2f}", style="bold red")
    body.append(f"  <  floor {floor:.2f}\n", style="grey70")
    if reason:
        body.append(reason, style="yellow")
    return Panel(body, title="GOVERNANCE CIRCUIT BREAKER", border_style="red",
                 box=ROUNDED, padding=(1, 2))


def prod_unlock_panel(reputation: float, floor: float) -> Panel:
    """Shown after the agent earns reputation back above the floor."""
    body = Text()
    body.append("  PRODUCTION ACCESS RESTORED\n\n", style="bold green")
    body.append("reputation  ", style="bold")
    body.append(f"{reputation:.2f}", style="bold green")
    body.append(f"  >=  floor {floor:.2f}\n", style="grey70")
    body.append("write_crm re-enabled - the agent earned its way back.", style="green")
    return Panel(body, title="GOVERNANCE - lock cleared", border_style="green",
                 box=ROUNDED, padding=(1, 2))


def prompt_diff_panel(before: str, after: str,
                      title: str = "OPTIMIZER - skill rewrite") -> Panel:
    """Unified diff of the SKILL.md the agent rewrote for itself."""
    diff = difflib.unified_diff(
        before.splitlines(), after.splitlines(),
        fromfile="SKILL.md (regressed)", tofile="SKILL.md (self-optimized)", lineterm="",
    )
    body = Text()
    for line in diff:
        if line.startswith("+") and not line.startswith("+++"):
            body.append(line + "\n", style="green")
        elif line.startswith("-") and not line.startswith("---"):
            body.append(line + "\n", style="red")
        elif line.startswith("@@"):
            body.append(line + "\n", style="cyan")
        else:
            body.append(line + "\n", style="grey50")
    if not body.plain.strip():
        body.append("(no textual change)\n", style="grey50")
    return Panel(body, title=title, border_style="magenta", box=ROUNDED)


def divider(label: str = "") -> Text:
    """Horizontal divider with optional label."""
    text = Text()
    if label:
        text.append(f"\n{'─'*20} ", style="grey50")
        text.append(label, style="bold grey70")
        text.append(f" {'─'*20}\n", style="grey50")
    else:
        text.append(f"\n{'─'*60}\n", style="grey50")
    return text
