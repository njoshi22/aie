"""
Main agent runner — executes one reconciliation session via Antigravity.
Usage: source .venv/bin/activate && GEMINI_API_KEY=... python -m agent.runner --session 1
"""
import os
import json
import argparse
from pathlib import Path
from google import genai

from agent.templates.agents_md import AGENTS_MD
from agent.templates.skill_md import generate_skill_md
from agent.prompts import build_reconciliation_prompt, build_cold_start_prompt
from agent.scenarios import SCENARIOS
from agent import revmem_client
from agent.tools import get_tools_for_tier
from evals import behaviors
from evals.gold import build_gold
from evals.grade import grade

DATA_DIR = Path(__file__).parent / "data"
AGENT_MODEL = "antigravity-preview-05-2026"
AGENT_NAME = "RevOps Finance Agent"  # matches Person B's seed; resolved get-or-create by name


def load_deal_data(deal_name: str) -> tuple[dict, dict, dict]:
    contract = json.loads((DATA_DIR / f"{deal_name}_contract.json").read_text())
    crm = json.loads((DATA_DIR / f"{deal_name}_crm.json").read_text())
    policy = json.loads((DATA_DIR / "policy.json").read_text())
    return contract, crm, policy


def build_environment(
    contract: dict,
    crm: dict,
    policy: dict,
    skill_content: str,
    agents_md: str,
) -> dict:
    return {
        "type": "remote",
        "sources": [
            {
                "type": "inline",
                "target": ".agents/AGENTS.md",
                "content": agents_md,
            },
            {
                "type": "inline",
                "target": ".agents/skills/reconciliation/SKILL.md",
                "content": skill_content,
            },
            {
                "type": "inline",
                "target": "/workspace/contract.json",
                "content": json.dumps(contract, indent=2),
            },
            {
                "type": "inline",
                "target": "/workspace/crm_record.json",
                "content": json.dumps(crm, indent=2),
            },
            {
                "type": "inline",
                "target": "/workspace/policy.json",
                "content": json.dumps(policy, indent=2),
            },
        ],
    }


def _execute_tool(name: str, arguments: dict, agent_id: str, session_id: str) -> dict:
    """Execute a tool call against RevMem and return the result as a dict."""
    if name == "retrieve_context":
        memories = revmem_client.retrieve_context(
            agent_id, arguments.get("query", ""),
        )
        return {"memories": memories, "count": len(memories)}

    if name == "store_memory":
        mem = revmem_client.store_memory(
            session_id, agent_id,
            arguments.get("memory_type", "lesson"),
            arguments.get("content", ""),
            {},
        )
        return {"stored": True, "memory_id": mem.get("id", "unknown")}

    if name == "route_for_approval":
        result = revmem_client.route_for_approval(
            arguments.get("deal_id", ""),
            arguments.get("amount_usd", 0),
            arguments.get("change_type", ""),
            summary=arguments.get("summary", ""),
        )
        return result

    # Antigravity sandbox has built-in tools (read_file, etc.) — skip unknown ones
    return {"error": f"Unknown tool: {name}", "note": "Not a RevMem tool"}


def run_session(
    session_number: int,
    env_id: str | None = None,
    prev_interaction_id: str | None = None,
    stream: bool = True,
) -> dict:
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    scenario = SCENARIOS[session_number]

    contract, crm, policy = load_deal_data(scenario["deal"])

    # Get-or-create the agent in RevMem (idempotent by name → stable id across runs)
    agent_state = revmem_client.ensure_agent(AGENT_NAME)
    agent_id = agent_state["id"]
    tier = agent_state["permission_tier"]

    print(f"\n{'='*60}")
    print(f"SESSION {session_number}")
    print(f"Deal: {scenario['deal'].upper()} | Tier: {tier.upper()} | Rep: {agent_state['reputation_score']}")
    print(f"Task: {scenario['task']}")
    print(f"{'='*60}\n")

    # Start RevMem session
    session = revmem_client.start_session(agent_id, scenario["task"])
    session_id = session["id"]

    # Build prompt — no pre-fetched memories; agent will call retrieve_context itself
    if scenario["prompt_style"] == "cold_start":
        prompt = build_cold_start_prompt(contract, crm)
    else:
        prompt = build_reconciliation_prompt(contract, crm, policy, [], tier)

    # Generate tier-scoped SKILL.md and tools
    skill_content = generate_skill_md(tier)
    tools = get_tools_for_tier(tier)

    # Build Antigravity environment
    environment = build_environment(contract, crm, policy, skill_content, AGENTS_MD)

    # --- Antigravity interaction with tool call loop ---
    print("Sending to Antigravity agent...")
    create_kwargs = {
        "agent": AGENT_MODEL,
        "input": prompt,
        "tools": tools,
    }

    if env_id:
        create_kwargs["environment"] = env_id
    else:
        create_kwargs["environment"] = environment

    if prev_interaction_id:
        create_kwargs["previous_interaction_id"] = prev_interaction_id

    interaction = client.interactions.create(**create_kwargs)
    memories_used = 0
    tool_calls_made = []

    max_tool_rounds = 3
    for _ in range(max_tool_rounds):
        if interaction.status != "requires_action":
            break

        fc_steps = [
            s.to_dict() for s in interaction.steps
            if s.to_dict().get("type") == "function_call"
        ]
        if not fc_steps:
            break

        results = []
        for fc in fc_steps:
            tool_name = fc["name"]
            tool_args = fc.get("arguments", {})
            print(f"  [tool] {tool_name}({json.dumps(tool_args)})")
            tool_calls_made.append(tool_name)

            tool_result = _execute_tool(tool_name, tool_args, agent_id, session_id)

            if tool_name == "retrieve_context":
                mems = tool_result.get("memories", [])
                memories_used += len(mems)
                if mems:
                    for m in mems:
                        print(f"    memory: {m.get('content', '')[:80]}")
                else:
                    print("    (no memories found)")

            results.append({
                "type": "function_result",
                "call_id": fc["id"],
                "name": tool_name,
                "result": tool_result,
            })

        # Continue WITHOUT tools to prevent infinite retry loop
        interaction = client.interactions.create(
            agent=AGENT_MODEL,
            previous_interaction_id=interaction.id,
            environment=interaction.environment_id,
            input=results,
        )

    output = interaction.output_text or "(no text output)"
    if tool_calls_made:
        print(f"  Tools called: {', '.join(tool_calls_made)}")
    print(f"\nAgent response:\n{output[:1500]}\n")

    # Grade the agent's ACTUAL output against gold labels derived from the data,
    # instead of trusting scenario["expected"]. Falls back to modeled behavior
    # only when the transcript yields no parseable decisions (e.g. offline stub).
    decisions = behaviors.decisions_from_output(output)
    graded_from_output = bool(decisions)
    if not decisions:
        step = f"{scenario['deal']}_{'cold' if scenario['prompt_style'] == 'cold_start' else 'learned'}"
        try:
            decisions = behaviors.modeled(step)
        except KeyError:
            decisions = []
    scorecard = grade(scenario["deal"], decisions, build_gold(scenario["deal"]))
    outcome = scorecard.outcome

    result = {
        "session_number": session_number,
        "session_id": session_id,
        "deal": scenario["deal"],
        "tier": tier,
        "reputation": agent_state["reputation_score"],
        "memories_used": memories_used,
        "agent_output": output,
        "interaction_id": interaction.id,
        "environment_id": interaction.environment_id,
        "outcome": outcome,
        "graded_from_output": graded_from_output,
    }

    # Close the session in RevMem with the MEASURED outcome (updates reputation +
    # memory relevance).
    revmem_client.complete_session(session_id, outcome)

    source = "agent output" if graded_from_output else "modeled fallback (no parseable decisions)"
    print(f"\nGraded outcome ({source}): {json.dumps(outcome)}")
    for note in scorecard.notes:
        print(f"  - {note}")
    print(f"Expected (designed): {scenario['expected']['description']}")
    print(f"Environment ID: {interaction.environment_id}")

    return result


def main():
    parser = argparse.ArgumentParser(description="Run a RevMem reconciliation session")
    parser.add_argument("--session", type=int, required=True, choices=[1, 2, 3])
    parser.add_argument("--env-id", type=str, default=None)
    parser.add_argument("--prev-interaction", type=str, default=None)
    parser.add_argument("--no-stream", action="store_true", help="Disable streaming output")
    args = parser.parse_args()

    result = run_session(args.session, args.env_id, args.prev_interaction, stream=not args.no_stream)
    print(f"\n--- Session {args.session} complete ---")
    print(json.dumps({k: v for k, v in result.items() if k != "agent_output"}, indent=2))


if __name__ == "__main__":
    main()
