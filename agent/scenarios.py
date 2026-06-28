"""Demo scenario definitions and expected outcomes."""

SCENARIOS = {
    1: {
        "deal": "acme",
        "task": "Reconcile Acme Corp signed contract against CRM record",
        "prompt_style": "cold_start",
        "expected": {
            "material_caught": 0,
            "false_escalations": 1,
            "accuracy": 0.0,
            "description": (
                "Cold start. Agent sees TCV matches, declares success. "
                "Escalates $0.33 rounding to CFO. Misses the ramp schedule mismatch."
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
                "With ramp lesson from S1. Agent ignores rounding noise, "
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
