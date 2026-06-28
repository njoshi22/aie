"""Pin the grader + gold math. Run: python -m evals.test_grade  (or pytest)."""

from __future__ import annotations

from evals import behaviors, harness
from evals.gold import build_gold, gold_counts
from evals.grade import Decision, grade


def test_gold_materiality():
    acme = gold_counts(build_gold("acme"))
    assert acme == {"material_total": 1, "immaterial_total": 1}, acme
    # Globex has TWO material items: the ramp AND the 25%-over-20% discount.
    globex = gold_counts(build_gold("globex"))
    assert globex == {"material_total": 2, "immaterial_total": 1}, globex


def test_routing_targets():
    g = {item.field: item for item in build_gold("acme")}
    assert g["annual_schedule_usd"].expected_route == "controller"
    assert g["y1_monthly_invoice_usd"].expected_action == "dismiss"
    gg = {item.field: item for item in build_gold("globex")}
    assert gg["discount_pct"].expected_route == "cfo_cco"


def test_cold_start_scores_zero():
    sc = grade("acme", behaviors.modeled("acme_cold"), build_gold("acme"))
    assert sc.material_caught == 0
    assert sc.false_escalations == 1     # over-escalated the rounding
    assert sc.accuracy == 0.0


def test_learned_scores_perfect():
    sc = grade("acme", behaviors.modeled("acme_learned"), build_gold("acme"))
    assert sc.material_recall == 1.0
    assert sc.false_escalations == 0
    assert sc.routing_accuracy == 1.0
    assert sc.accuracy == 1.0


def test_misrouting_gets_partial_credit():
    # Caught the ramp but sent it to the CFO instead of the Controller.
    sc = grade("acme", [Decision("annual_schedule_usd", "escalate", route_to="cfo"),
                        Decision("y1_monthly_invoice_usd", "dismiss")], build_gold("acme"))
    assert sc.material_caught == 1 and sc.routing_correct == 0
    assert sc.accuracy == 0.75   # 0.5 (half credit) + 1 immaterial, over 2 items


def test_generalization_holds_on_unseen_deal():
    sc = grade("globex", behaviors.modeled("globex_learned"), build_gold("globex"))
    assert sc.material_recall == 1.0          # both material items caught
    assert sc.false_escalations == 0


def test_harness_curve_improves_and_ablation_positive():
    rep = harness.run()
    accs = [row["accuracy"] for row in rep["curve"]]
    assert accs == sorted(accs)               # non-decreasing learning curve
    assert accs[0] == 0.0 and accs[1] == 1.0  # S1 cold fails, S2 learned perfect
    assert rep["ablation"]["accuracy_gain"] > 0.0
    assert rep["generalization"]["material_recall_on_unseen_deal"] == 1.0


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")


if __name__ == "__main__":
    _run_all()
