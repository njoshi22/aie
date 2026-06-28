"""Entry point: run the continual-learning evals and print + save the report.

    uv run python -m evals.run                 # modeled (offline, no API calls)
    uv run python -m evals.run --json-only     # just write evals/report.json
    uv run python -m evals.run --out path.json # custom output path

At integration, pass real agent transcripts to ``harness.run({step: text})`` so
decisions are parsed from actual output instead of the modeled behaviors.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evals import harness, report

DEFAULT_OUT = Path(__file__).resolve().parent / "report.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="RevMem continual-learning evals")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="where to write the JSON report")
    parser.add_argument("--json-only", action="store_true", help="skip the CLI render")
    args = parser.parse_args()

    result = harness.run()
    args.out.write_text(json.dumps(result, indent=2))

    if not args.json_only:
        report.render(result)
    print(f"report written to {args.out}")


if __name__ == "__main__":
    main()
