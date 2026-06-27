"""RevMem human-in-the-loop email approval (Person C).

When RevMem finishes a session and routes a material discrepancy to the CFO,
``email.py`` sends exactly one approval email with an Approve magic link, and
``approve.py`` exposes the ``/approve/{token}`` endpoint plus the approval-state
store the CLI polls before executing the CRM write.
"""
