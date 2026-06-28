"""RevMem evals - measure whether continual learning actually improves the agent.

The runner currently closes each session with a hardcoded ``scenario["expected"]``
outcome. These evals instead *grade the agent's real decisions* against gold
labels derived from the contract/CRM/policy data, then track the metrics across
sessions so "the agent gets better" becomes a measured claim, not an asserted one.

Headline metrics (per session, then as a curve):
    material_recall      caught material discrepancies / all material  (should rise)
    false_escalations    immaterial/matched fields wrongly escalated   (should fall)
    routing_accuracy     correct approver among caught material        (should rise)
    accuracy             composite 0..1 (feeds reputation)             (should rise)

Two causal cuts that isolate RevMem's contribution:
    ablation        same deal + same permissions, memory ON vs OFF
    generalization  does the learned lesson transfer to an unseen deal
"""
