from core import reputation
from core.models import PermissionTier


def test_tier_boundaries():
    assert reputation.tier_for(0.0) == PermissionTier.OBSERVER
    assert reputation.tier_for(0.29) == PermissionTier.OBSERVER
    assert reputation.tier_for(0.3) == PermissionTier.ANALYST
    assert reputation.tier_for(0.59) == PermissionTier.ANALYST
    assert reputation.tier_for(0.6) == PermissionTier.AUTONOMOUS
