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
