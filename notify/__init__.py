"""RevMem human-in-the-loop email approval (Person C).

When RevMem finishes a session and routes a material discrepancy to the CFO,
``email.py`` sends exactly one approval email with an Approve magic link, and
``approve.py`` exposes the approval endpoints (``GET /approvals/{id}`` confirm
page, ``POST /approvals/{id}/decision``, ``GET /approvals/{id}/status``) plus the
approval-state store — mirroring Person B's contract until the RevMem API serves it.
"""
