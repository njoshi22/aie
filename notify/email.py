"""Compose and send the single CFO approval email (Resend).

One email per session: discrepancy + recommended fix + an Approve magic link
(-> notify.approve:/approve/{token}). Falls back to a console dry-run when
RESEND_API_KEY is unset, so the whole flow runs without credentials.

Env:
    RESEND_API_KEY      resend.com api key (omit for dry-run)
    REVMEM_FROM_EMAIL   verified sender (default onboarding@resend.dev for tests)
"""

from __future__ import annotations

import os

from notify.approve import ApprovalRequest


def _amount_row(approval: ApprovalRequest) -> str:
    if approval.amount_usd is None:
        return ""
    return (
        '<tr><td style="padding:8px 0;color:#777">Amount at issue</td>'
        f'<td style="padding:8px 0;text-align:right">${approval.amount_usd:,.2f}</td></tr>'
    )


def render_html(approval: ApprovalRequest) -> str:
    url = approval.approve_url()
    return f"""\
<div style="font-family:Inter,Arial,sans-serif;background:#F5F3EE;padding:32px;color:#1B2A16">
  <div style="max-width:520px;margin:0 auto;background:#fff;border-radius:12px;padding:32px">
    <h1 style="font-family:Georgia,serif;font-size:22px;margin:0 0 4px">RevMem needs your sign-off</h1>
    <p style="color:#555;margin:0 0 24px">Deal {approval.deal_id} reconciliation finished. One item needs CFO approval.</p>
    <table style="width:100%;border-collapse:collapse;font-size:14px;margin:0 0 24px">
      <tr><td style="padding:8px 0;color:#777">Discrepancy</td><td style="padding:8px 0;text-align:right">{approval.discrepancy}</td></tr>
      <tr><td style="padding:8px 0;color:#777">Recommended fix</td><td style="padding:8px 0;text-align:right">{approval.recommended_fix}</td></tr>
      {_amount_row(approval)}
    </table>
    <a href="{url}" style="display:inline-block;background:#4E6639;color:#fff;text-decoration:none;padding:12px 28px;border-radius:8px;font-weight:600">Approve correction</a>
    <p style="color:#999;font-size:12px;margin:24px 0 0">RevMem - governed agent memory. You are the only approver on this request.</p>
  </div>
</div>"""


def render_text(approval: ApprovalRequest) -> str:
    lines = [
        "RevMem needs your sign-off.",
        f"Deal {approval.deal_id} reconciliation finished. One item needs CFO approval.",
        "",
        f"  Discrepancy:     {approval.discrepancy}",
        f"  Recommended fix: {approval.recommended_fix}",
    ]
    if approval.amount_usd is not None:
        lines.append(f"  Amount at issue: ${approval.amount_usd:,.2f}")
    lines += ["", f"Approve: {approval.approve_url()}"]
    return "\n".join(lines)


def send_approval_email(approval: ApprovalRequest) -> dict:
    """Send the single approval email. Returns the provider response (or a
    dry-run marker when no API key is set)."""
    subject = f"[RevMem] Approval needed - {approval.deal_id} reconciliation"
    api_key = os.environ.get("RESEND_API_KEY")
    sender = os.environ.get("REVMEM_FROM_EMAIL", "onboarding@resend.dev")

    if not api_key:
        print("\n[dry-run email] RESEND_API_KEY not set - would send:")
        print(f"  to:      {approval.approver_email}")
        print(f"  from:    {sender}")
        print(f"  subject: {subject}")
        print(render_text(approval))
        print()
        return {"id": "dry-run", "dry_run": True, "approve_url": approval.approve_url()}

    import resend

    resend.api_key = api_key
    return resend.Emails.send(
        {
            "from": sender,
            "to": [approval.approver_email],
            "subject": subject,
            "html": render_html(approval),
            "text": render_text(approval),
        }
    )
