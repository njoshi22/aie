"""Where decisions come from.

Two sources:
  1. ``decisions_from_output`` - parse a real agent transcript. The agent emits
     the AGENTS.md schema (``fields_compared`` array of {field, match,
     materiality, recommended_action, route_to, ...}); we also accept a bare
     ``DECISIONS: [...]`` array as a fallback wire format.
  2. ``MODELED`` - scripted per-session behavior mirroring the demo narrative, so
     the eval runs fully offline and the learning curve is reproducible without
     spending Gemini calls. Used only when no decisions can be parsed.
"""

from __future__ import annotations

import json
import re

from evals.grade import Decision

# AGENTS.md recommended_action -> grader action
_ACTION_MAP = {
    "escalate": "escalate",
    "auto_resolve": "reconcile",   # acted on it (AM-level fix) -> counts as caught
    "auto_dismiss": "dismiss",
    "flag": "flag",
    "dismiss": "dismiss",
    "reconcile": "reconcile",
}

# --- Modeled behavior per demo step ------------------------------------------
# Keyed by a step label; the harness maps sessions -> steps. Mirrors the
# ARCHITECTURE.md scenario: S1 cold (miss ramp, over-escalate rounding),
# S2 learned on Acme, S3 lesson generalizes to Globex (+ over-authority discount).

MODELED: dict[str, list[Decision]] = {
    # Acme, cold start: misses the ramp, escalates the $0.33 rounding to the CFO.
    "acme_cold": [
        Decision("annual_schedule_usd", "miss"),
        Decision("y1_monthly_invoice_usd", "escalate", route_to="cfo"),
    ],
    # Acme, with the ramp lesson: dismiss rounding, catch ramp, route to Controller.
    "acme_learned": [
        Decision("annual_schedule_usd", "escalate", route_to="controller"),
        Decision("y1_monthly_invoice_usd", "dismiss"),
    ],
    # Globex (unseen), lesson generalizes: catch ramp (Controller), escalate the
    # 25%-over-20% discount to CFO/CCO, dismiss rounding.
    "globex_learned": [
        Decision("annual_schedule_usd", "escalate", route_to="controller"),
        Decision("discount_pct", "escalate", route_to="cfo_cco"),
        Decision("y1_monthly_invoice_usd", "dismiss"),
    ],
}


def modeled(step: str) -> list[Decision]:
    return list(MODELED[step])


def _norm_route(route) -> str | None:
    if route in (None, "", "null", "none", "None"):
        return None
    return str(route)


def _field_to_decision(d: dict) -> Decision | None:
    """Map one AGENTS.md ``fields_compared`` entry to a grader Decision."""
    field = d.get("field")
    if not field:
        return None
    raw_action = d.get("recommended_action")
    if raw_action:
        action = _ACTION_MAP.get(str(raw_action), "flag")
    elif d.get("match") is True:
        action = "match"            # neutral: not caught, not escalating
    else:
        action = "flag"             # mismatch noted, no explicit action
    return Decision(field=str(field), action=action, route_to=_norm_route(d.get("route_to")))


def _extract_json_object(text: str) -> dict | None:
    """Pull the agent's JSON object out of free-form text (fenced or inline)."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidates = []
    if fenced:
        candidates.append(fenced.group(1))
    start = text.find("{")
    while start != -1:                       # brace-match the first balanced object
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    candidates.append(text[start : i + 1])
                    break
        break
    for blob in candidates:
        try:
            obj = json.loads(blob)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue
    return None


_DECISIONS_RE = re.compile(r"DECISIONS:\s*(\[.*?\])", re.DOTALL)


def decisions_from_output(text: str) -> list[Decision]:
    """Parse a real agent transcript into Decisions.

    Prefers the AGENTS.md ``fields_compared`` schema; falls back to a bare
    ``DECISIONS: [...]`` array. Returns [] when nothing parses, so the caller can
    fall back to a modeled step and flag it.
    """
    text = text or ""

    obj = _extract_json_object(text)
    if obj and isinstance(obj.get("fields_compared"), list):
        out = [_field_to_decision(d) for d in obj["fields_compared"] if isinstance(d, dict)]
        return [d for d in out if d]

    m = _DECISIONS_RE.search(text)
    if m:
        try:
            raw = json.loads(m.group(1))
        except json.JSONDecodeError:
            raw = []
        return [
            Decision(str(d["field"]), str(d.get("action", "miss")), _norm_route(d.get("route_to")))
            for d in raw
            if isinstance(d, dict) and d.get("field")
        ]

    return []
