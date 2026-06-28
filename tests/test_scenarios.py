from __future__ import annotations

from agent.scenarios import SCENARIOS
from evals.gold import build_gold


def test_session_three_expected_material_count_matches_gold() -> None:
    material_total = sum(1 for item in build_gold("globex") if item.material)
    expected = SCENARIOS[3]["expected"]

    assert isinstance(expected, dict)
    assert expected["material_caught"] == material_total
