# ADR-0001: Continuous Interaction Chain with Live Human Correction

## Status

Accepted — 2026-06-27

## Context

The original demo ran three independent sessions via `python -m cli.run --live --all`. Each session was a separate `interactions.create` call with a pre-written prompt. The "learning" between sessions was a hardcoded `reviewer_lesson` in `scenarios.py`, injected server-side at session completion — no human involvement.

This created two problems:

1. **The learning was fake.** The lesson was pre-written regardless of what the agent actually did in S1. Evaluators examining the code would see the choreography.
2. **The architecture underused Antigravity.** Three independent API calls looked like a "standard wrapper" around the Interactions API, not a demonstration of stateful agent evolution — which is what the Gemini prize criteria explicitly asks for.

## Decision

Restructure the demo as **one continuous interaction chain** with human correction in the middle:

```
interaction_1: "Reconcile Acme" (full data + policy, no memories)
  → agent makes judgment errors (wrong routing, over-escalation)
interaction_2: human types correction in CLI → passed as input
  → agent autonomously calls store_memory
interaction_3: "Reconcile Globex" (new deal)
  → agent calls retrieve_context, retrieves lesson from interaction_2
  → demonstrates generalized learning on unseen data
```

All interactions share one `environment_id`. The environment contains only agent config (`AGENTS.md`, `SKILL.md`); deal data is inlined in each prompt.

### Key design choices within this decision:

- **Judgment-based errors, not information-gap errors.** S1 gets complete data + DOA policy. The agent errs because it lacks experiential context to interpret edge cases (e.g., classifying schedule distribution changes, handling sub-$1 rounding). This replaces the old `cold_start` prompt that deliberately stripped `annual_schedule_usd`.
- **Agent owns `store_memory`.** Human correction is passed as natural language input to the next interaction. The agent decides what to store via its `store_memory` tool call. The runner does not store on the agent's behalf.
- **Cross-deal generalization.** Acme → correction → Globex proves the lesson transfers, not that the agent memorized one deal's answer.
- **Two parallel implementations.** Path 1 (runner with inter-session CLI input) and Path 2 (continuous interaction chain) are both built; the better-performing one is selected for the final demo.

## Consequences

- `build_cold_start_prompt` is deleted; `build_reconciliation_prompt` handles all sessions with memories as an empty list for S1.
- `scenarios.py` `reviewer_lesson` field becomes unused (kept for offline eval fallback).
- Demo reliability depends on the agent actually calling `store_memory` and `retrieve_context` correctly. Prompt engineering in `AGENTS.md` must reinforce this.
- The `environment_id` reset on deal change (`demo.py`) is removed for the continuous chain path.
- The existing eval/grading pipeline (`gold.py`, `grade.py`) continues to work — it grades agent output against gold labels regardless of how the session was triggered.
