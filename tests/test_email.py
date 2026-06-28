from notify.approve import ApprovalRequest
from notify.email import render_text


def test_approval_email_uses_routed_role():
    approval = ApprovalRequest(
        deal_id="GLOBEX-2026",
        approver_role="controller",
        approver_email="controller@example.com",
        discrepancy="Schedule mismatch",
        recommended_fix="Align the annual schedule",
    )

    text = render_text(approval)

    assert "needs Controller approval" in text
    assert "needs CFO approval" not in text


def test_approval_email_formats_joint_route():
    approval = ApprovalRequest(
        deal_id="GLOBEX-2026",
        approver_role="cfo_cco",
        approver_email="approval@example.com",
        discrepancy="Discount over authority",
        recommended_fix="Review discount exception",
    )

    assert "needs CFO + CCO approval" in render_text(approval)
