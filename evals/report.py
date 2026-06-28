"""Render the eval as a CLI learning-curve report (Person C's CLI-forward style).

The same numbers also serialize to JSON for the agent runner / UI to consume.
"""

from __future__ import annotations

from rich.box import ROUNDED, SIMPLE
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


def _bar(value: float, width: int = 12, color: str = "green") -> Text:
    filled = int(round(max(0.0, min(1.0, value)) * width))
    t = Text()
    t.append("#" * filled, style=color)
    t.append("." * (width - filled), style="grey37")
    return t


def render(report: dict, console: Console | None = None) -> None:
    console = console or Console()

    console.print()
    console.print(
        Panel(
            Text(
                "Continual-learning evals - does RevMem make the agent better across sessions?",
                style="bold",
            ),
            subtitle=f"source: {report['source']}",
            box=ROUNDED,
            border_style="blue",
        )
    )

    # --- Learning curve table -------------------------------------------------
    table = Table(title="Learning curve", title_style="bold", box=ROUNDED, expand=True)
    table.add_column("S")
    table.add_column("Deal")
    table.add_column("Tier")
    table.add_column("Mem")
    table.add_column("Accuracy")
    table.add_column("Material recall")
    table.add_column("False esc.", justify="right")
    table.add_column("Routing")
    for r in report["curve"]:
        acc = Text()
        acc.append_text(_bar(r["accuracy"]))
        acc.append(f" {r['accuracy']:.2f}")
        rec = Text()
        rec.append_text(_bar(r["material_recall"], color="cyan"))
        rec.append(f" {r['material']}")
        fe_style = "green" if r["false_escalations"] == 0 else "red"
        table.add_row(
            str(r["session"]),
            r["deal"],
            r["tier"].upper(),
            "on" if r["memory"] else "off",
            acc,
            rec,
            Text(str(r["false_escalations"]), style=fe_style),
            f"{r['routing_accuracy']:.2f}",
        )
    console.print(table)

    # --- Causal callouts ------------------------------------------------------
    abl = report["ablation"]
    abl_body = Text()
    abl_body.append("same deal (acme), tier held OBSERVER, only memory toggled\n\n", style="grey70")
    abl_body.append("memory ON   ", style="bold")
    abl_body.append(f"accuracy {abl['memory_on']['accuracy']:.2f}   recall {abl['memory_on']['material_caught']}/{abl['memory_on']['material_total']}\n", style="green")
    abl_body.append("memory OFF  ", style="bold")
    abl_body.append(f"accuracy {abl['memory_off']['accuracy']:.2f}   recall {abl['memory_off']['material_caught']}/{abl['memory_off']['material_total']}\n", style="red")
    abl_body.append("\nRevMem gain ", style="bold")
    abl_body.append(f"+{abl['accuracy_gain']:.2f} accuracy   +{abl['recall_gain']:.2f} recall", style="bold green")
    console.print(Panel(abl_body, title="Ablation - isolates RevMem's contribution", border_style="magenta", box=ROUNDED))

    gen = report["generalization"]
    gen_body = Text()
    gen_body.append(f"trained on {gen['trained_on']}  ->  evaluated on unseen {gen['evaluated_on']}\n\n", style="grey70")
    gen_body.append("material recall on unseen deal  ", style="bold")
    gen_body.append(f"{gen['material_recall_on_unseen_deal']:.2f}\n", style="bold green")
    gen_body.append("false escalations on unseen deal ", style="bold")
    gen_body.append(str(gen["false_escalations_on_unseen_deal"]), style="green")
    console.print(Panel(gen_body, title="Generalization - lesson transfers, not memorized", border_style="cyan", box=ROUNDED))

    # --- One-line verdict -----------------------------------------------------
    d = report["deltas"]
    verdict = Text()
    verdict.append("S1->S2 ", style="bold")
    verdict.append(f"accuracy +{d['s1_to_s2']['accuracy']:.2f}, false-esc {d['s1_to_s2']['false_escalations']:+d}  (context only)\n", style="green")
    verdict.append("S2->S3 ", style="bold")
    verdict.append(f"accuracy {d['s2_to_s3']['accuracy']:+.2f} on an unseen deal  (generalized + autonomy grew)", style="green")
    console.print(Panel(verdict, box=SIMPLE))
    console.print()


def render_retrieval(result: dict, console: Console | None = None) -> None:
    """Render the retrieval-quality eval (does RevMem surface the right lesson?)."""
    console = console or Console()
    q = result["quality"]
    abl = result["ablation"]

    table = Table(title="Retrieval quality - right lesson for the task?", title_style="bold",
                  box=ROUNDED, expand=True)
    table.add_column("Probe (relevant lesson)")
    table.add_column("Rank", justify="right")
    table.add_column("Top hit")
    for p in q["per_probe"]:
        rank = p["rank"]
        style = "green" if rank == 1 else ("yellow" if rank and rank <= 3 else "red")
        table.add_row(p["relevant"], Text(str(rank), style=style), (p["top"] or "")[:48])
    console.print()
    console.print(table)

    head = Text()
    head.append(f"hit@1 {q['hit@1']:.2f}   hit@3 {q['hit@3']:.2f}   MRR {q['mrr']:.2f}", style="bold")
    console.print(Panel(head, box=SIMPLE))

    body = Text()
    body.append(f"{abl['scenario']}\n", style="grey70")
    body.append(f"query: {abl['query']}\n\n", style="grey70")
    body.append("trusted lesson rank   ", style="bold")
    body.append(f"learned {abl['learned_rank']}   flat {abl['flat_rank']}\n",
                style="green" if abl["rank_improved"] else "grey50")
    body.append("reputation-driven lift ", style="bold")
    body.append(f"+{abl['mrr_lift']:.2f} MRR", style="bold green" if abl["mrr_lift"] > 0 else "grey50")
    console.print(Panel(body, title="Ablation - outcome-based relevance improves retrieval",
                        border_style="magenta", box=ROUNDED))
    console.print()


def render_live(summary: dict, console: Console | None = None) -> None:
    """Render a learning curve built from REAL persisted outcomes (DB/API)."""
    console = console or Console()
    console.print()
    console.print(Panel(Text(f"Live learning curve from real outcomes  (source: {summary.get('source','?')})",
                             style="bold"), box=ROUNDED, border_style="blue"))
    if summary.get("n", 0) == 0:
        console.print(Panel(Text("No completed sessions found yet - run a live demo first.", style="yellow"),
                            box=SIMPLE))
        console.print()
        return

    table = Table(box=ROUNDED, expand=True)
    table.add_column("#", justify="right")
    table.add_column("Accuracy")
    table.add_column("Material recall")
    table.add_column("False esc.", justify="right")
    table.add_column("Routing", justify="right")
    for p in summary["curve"]:
        acc = p["accuracy"]
        acc_cell = Text()
        acc_cell.append_text(_bar(acc))
        acc_cell.append(f" {acc:.2f}")
        has_recall = p.get("material_total") and p.get("material_caught") is not None
        recall = f"{int(p['material_caught'])}/{int(p['material_total'])}" if has_recall else "-"
        ra = p.get("routing_accuracy")
        table.add_row(str(p["index"]), acc_cell, recall,
                      str(p.get("false_escalations", "?")),
                      f"{ra:.2f}" if ra is not None else "-")
    console.print(table)

    if summary.get("n", 0) >= 2:
        d = summary["deltas"]
        line = Text()
        line.append("first -> last  ", style="bold")
        line.append(f"accuracy {summary['first']['accuracy']:.2f} -> {summary['last']['accuracy']:.2f}", style="green")
        if d.get("false_escalations") is not None:
            line.append(f"   false-esc {d['false_escalations']:+d}", style="green")
        console.print(Panel(line, box=SIMPLE))
    console.print()
