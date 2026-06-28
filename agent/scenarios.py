"""Demo scenario definitions and expected outcomes."""

SCENARIOS = {
    1: {
        "deal": "acme",
        "task": "Reconcile Acme Corp signed contract against CRM record",
        "prompt_style": "full",
        "expected": {
            "material_caught": 1,
            "false_escalations": 1,
            "accuracy": 0.5,
            "description": (
                "No prior memories. Agent catches the schedule mismatch but "
                "over-escalates the $0.33 rounding to CFO instead of auto-dismissing "
                "per DOA-001. May also mis-route the schedule change."
            ),
        },
    },
    2: {
        "deal": "acme",
        "task": "Reconcile Acme Corp signed contract against CRM record",
        "prompt_style": "full",
        "expected": {
            "material_caught": 1,
            "false_escalations": 0,
            "accuracy": 1.0,
            "description": (
                "With lesson from reviewer feedback. Agent dismisses rounding noise, "
                "catches the annual schedule mismatch, routes to Controller."
            ),
        },
    },
    3: {
        "deal": "globex",
        "task": "Reconcile Globex Inc signed contract against CRM and flag pipeline impacts",
        "prompt_style": "full",
        "expected": {
            "material_caught": 2,
            "false_escalations": 0,
            "accuracy": 1.0,
            "description": (
                "Lesson generalizes to new deal. Agent catches the ramp schedule mismatch "
                "and escalates the 25% discount over deal-desk authority to CFO/CCO."
            ),
        },
    },
}
