from core import governance
from core.models import PermissionTier, PolicyRule

RULES = [
    PolicyRule(description="rounding", condition={"min_usd": 0, "max_usd": 1000}, route_to="am"),
    PolicyRule(description="mid", condition={"min_usd": 1000, "max_usd": 50000}, route_to="controller"),
    PolicyRule(description="schedule", condition={"change_types": ["schedule_change"]}, route_to="cfo"),
    PolicyRule(description="discount", condition={"change_types": ["discount_over_authority"]}, route_to="cfo"),
]


def test_amount_band_routing():
    assert governance.route({"amount_usd": 12, "change_type": "amount_diff"}, RULES) == "am"
    assert governance.route({"amount_usd": 8000, "change_type": "amount_diff"}, RULES) == "controller"


def test_change_type_override_wins():
    # ramp restructuring keeps TCV identical (amount_usd 0) but is material → CFO
    assert governance.route({"amount_usd": 0, "change_type": "schedule_change"}, RULES) == "cfo"
    assert governance.route({"amount_usd": 5, "change_type": "discount_over_authority"}, RULES) == "cfo"


def test_tool_gating():
    assert not governance.can_use(PermissionTier.OBSERVER, "write_crm")
    assert governance.can_use(PermissionTier.ANALYST, "write_crm")
    assert governance.can_use(PermissionTier.OBSERVER, "retrieve_context")


def test_skill_md_grows_with_tier():
    obs = governance.generate_skill_md(PermissionTier.OBSERVER)
    auto = governance.generate_skill_md(PermissionTier.AUTONOMOUS)
    assert "write_crm" not in obs and "write_crm" in auto
