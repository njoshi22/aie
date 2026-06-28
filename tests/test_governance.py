import pytest

from core import governance
from core.approval_policy import (
    ApprovalJoin,
    ApprovalStatus,
    approval_plan_for_method,
    approval_request_satisfied,
    dependencies_satisfied,
)
from core.models import PermissionTier, PolicyRule

RULES = [
    PolicyRule(description="rounding", condition={"max_diff_usd": 1}, route_to=None, action="auto_dismiss"),
    PolicyRule(
        description="minor",
        condition={"min_diff_usd": 1, "max_diff_usd": 1000},
        route_to="am",
        action="auto_resolve",
    ),
    PolicyRule(
        description="mid",
        condition={"min_diff_usd": 1000, "max_diff_usd": 50000},
        route_to="controller",
    ),
    PolicyRule(
        description="schedule",
        condition={"min_diff_usd": 1000, "max_diff_usd": 50000, "change_types": ["schedule_change"]},
        route_to="controller",
    ),
    PolicyRule(description="discount", condition={"change_types": ["discount_over_authority"]}, route_to="cfo_cco"),
]


def test_amount_band_routing():
    assert governance.route({"amount_usd": 12, "change_type": "amount_diff"}, RULES) == "am"
    assert governance.route({"amount_usd": 8000, "change_type": "amount_diff"}, RULES) == "controller"


def test_change_type_override_wins():
    assert governance.route({"amount_usd": 40000, "change_type": "schedule_change"}, RULES) == "controller"
    assert governance.route({"amount_usd": 5, "change_type": "discount_over_authority"}, RULES) == "cfo_cco"


def test_tool_gating():
    assert not governance.can_use(PermissionTier.OBSERVER, "write_crm")
    assert not governance.can_use(PermissionTier.ANALYST, "write_crm")
    assert governance.can_use(PermissionTier.AUTONOMOUS, "write_crm")
    assert governance.can_use(PermissionTier.OBSERVER, "retrieve_context")


def test_skill_md_grows_with_tier():
    obs = governance.generate_skill_md(PermissionTier.OBSERVER)
    analyst = governance.generate_skill_md(PermissionTier.ANALYST)
    auto = governance.generate_skill_md(PermissionTier.AUTONOMOUS)
    assert "write_crm" not in obs
    assert "write_crm" not in analyst
    assert "write_crm" in auto


def test_crm_write_schedule_change_requires_controller_method_approval() -> None:
    plan = approval_plan_for_method(
        "crm.write",
        {
            "tier": "analyst",
            "discrepancy": {
                "deal_id": "globex",
                "amount_usd": 40000,
                "change_type": "schedule_change",
            },
        },
        RULES,
    )

    assert plan.required is True
    assert plan.join == ApprovalJoin.ALL
    assert [(step.step_id, step.role, step.depends_on) for step in plan.steps] == [
        ("controller", "controller", ()),
    ]


def test_crm_write_discount_requires_dependent_cfo_then_cco_approvals() -> None:
    plan = approval_plan_for_method(
        "crm.write",
        {
            "tier": "analyst",
            "discrepancy": {
                "deal_id": "globex",
                "amount_usd": 0,
                "change_type": "discount_over_authority",
            },
        },
        RULES,
    )

    assert plan.required is True
    assert plan.join == ApprovalJoin.ALL
    assert [(step.step_id, step.role, step.depends_on) for step in plan.steps] == [
        ("cfo", "cfo", ()),
        ("cco", "cco", ("cfo",)),
    ]


def test_policy_update_allows_any_finance_admin_or_controller() -> None:
    plan = approval_plan_for_method("policy.update", {"tier": "analyst"})

    assert plan.required is True
    assert plan.join == ApprovalJoin.ANY
    assert {step.role for step in plan.steps} == {"finance_admin", "controller"}


def test_non_sensitive_methods_are_explicitly_no_approval() -> None:
    plan = approval_plan_for_method("sessions.complete", {"tier": "observer"})

    assert plan.allowed is True
    assert plan.required is False
    assert plan.steps == ()


def test_observer_crm_write_is_denied_by_method_policy() -> None:
    plan = approval_plan_for_method(
        "crm.write",
        {
            "tier": "observer",
            "discrepancy": {
                "deal_id": "globex",
                "amount_usd": 40000,
                "change_type": "schedule_change",
            },
        },
        RULES,
    )

    assert plan.allowed is False
    assert plan.required is False
    assert plan.steps == ()


def test_crm_write_method_policy_requires_policy_rules() -> None:
    with pytest.raises(ValueError, match="policy rules"):
        approval_plan_for_method(
            "crm.write",
            {
                "tier": "analyst",
                "discrepancy": {
                    "deal_id": "globex",
                    "amount_usd": 40000,
                    "change_type": "schedule_change",
                },
            },
        )


def test_approval_join_and_dependencies_are_evaluated() -> None:
    approvals = [
        {"step_id": "cfo", "status": ApprovalStatus.APPROVED, "depends_on": ""},
        {"step_id": "cco", "status": ApprovalStatus.PENDING, "depends_on": "cfo"},
    ]

    assert approval_request_satisfied(ApprovalJoin.ALL, approvals) is False
    assert approval_request_satisfied(ApprovalJoin.ANY, approvals) is True
    assert dependencies_satisfied("cco", approvals) is True
    assert dependencies_satisfied("cfo", approvals) is True

    blocked = [
        {"step_id": "cfo", "status": ApprovalStatus.PENDING, "depends_on": ""},
        {"step_id": "cco", "status": ApprovalStatus.PENDING, "depends_on": "cfo"},
    ]
    assert dependencies_satisfied("cco", blocked) is False
