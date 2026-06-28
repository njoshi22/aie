"""Entry point for the RevMem continual-learning evals.

    uv run python -m evals.run                    # modeled learning curve (offline)
    uv run python -m evals.run --json-only         # just write evals/report.json
    uv run python -m evals.run retrieval           # retrieval-quality eval (hit@k, MRR, ablation)
    uv run python -m evals.run live                # learning curve from REAL outcomes (SQLite)
    uv run python -m evals.run live --source api   # ... read from a running API instead
    uv run python -m evals.run live --db db/revmem.db --agent <id>

`curve` (default) grades modeled/real session decisions; `live` reads the outcomes
the runner actually persisted, so the curve reflects what happened in real runs.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evals import harness, report

DEFAULT_OUT = Path(__file__).resolve().parent / "report.json"


def _cmd_curve(args: argparse.Namespace) -> None:
    result = harness.run()
    args.out.write_text(json.dumps(result, indent=2))
    if not args.json_only:
        report.render(result)
    print(f"report written to {args.out}")


def _cmd_retrieval(args: argparse.Namespace) -> None:
    from evals import retrieval

    result = retrieval.run()
    if args.json_only:
        print(json.dumps(result, indent=2))
    else:
        report.render_retrieval(result)


def _cmd_live(args: argparse.Namespace) -> None:
    from evals import live

    kwargs = {"agent_id": args.agent} if args.agent else {}
    if args.source == "db" and args.db:
        kwargs["db_path"] = args.db
    if args.source == "api" and args.base_url:
        kwargs["base_url"] = args.base_url
    summary = live.live_summary(source=args.source, **kwargs)
    if args.json_only:
        print(json.dumps(summary, indent=2))
    else:
        report.render_live(summary)


def main() -> None:
    # Shared so --json-only works both before and after the subcommand.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json-only", action="store_true", default=argparse.SUPPRESS,
                        help="emit JSON instead of the Rich render")

    parser = argparse.ArgumentParser(description="RevMem continual-learning evals", parents=[common])
    sub = parser.add_subparsers(dest="cmd")

    p_curve = sub.add_parser("curve", parents=[common], help="modeled/graded learning curve (default)")
    p_curve.add_argument("--out", type=Path, default=DEFAULT_OUT, help="where to write the JSON report")

    sub.add_parser("retrieval", parents=[common], help="retrieval-quality eval (hit@k, MRR, relevance ablation)")

    p_live = sub.add_parser("live", parents=[common], help="learning curve from real persisted outcomes")
    p_live.add_argument("--source", choices=["db", "api"], default="db")
    p_live.add_argument("--db", default=None, help="SQLite path (default: REVMEM_DB or db/revmem.db)")
    p_live.add_argument("--base-url", default=None, help="API base (default: REVMEM_BASE_URL)")
    p_live.add_argument("--agent", default=None, help="filter to one agent id")

    args = parser.parse_args()
    args.json_only = getattr(args, "json_only", False)  # SUPPRESS -> set only when passed
    if args.cmd == "retrieval":
        _cmd_retrieval(args)
    elif args.cmd == "live":
        _cmd_live(args)
    else:  # default / "curve"
        if not hasattr(args, "out"):
            args.out = DEFAULT_OUT
        _cmd_curve(args)


if __name__ == "__main__":
    main()
