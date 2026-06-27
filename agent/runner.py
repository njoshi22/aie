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

DATA_DIR = Path(__file__).parent / "data"
AGENT_MODEL = "antigravity-preview-05-2026"


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


def run_session(
    session_number: int,
    env_id: str | None = None,
    prev_interaction_id: str | None = None,
    stream: bool = True,
) -> dict:
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    scenario = SCENARIOS[session_number]

    contract, crm, policy = load_deal_data(scenario["deal"])

    # Get agent state from RevMem
    agent_state = revmem_client.get_agent("revops-agent-1")
    tier = agent_state["permission_tier"]

    print(f"\n{'='*60}")
    print(f"SESSION {session_number}")
    print(f"Deal: {scenario['deal'].upper()} | Tier: {tier.upper()} | Rep: {agent_state['reputation_score']}")
    print(f"Task: {scenario['task']}")
    print(f"{'='*60}\n")

    # Start RevMem session
    session = revmem_client.start_session("revops-agent-1", scenario["task"])
    session_id = session["id"]

    # Retrieve memories from RevMem
    memories = revmem_client.retrieve_context(
        "contract_reconciliation",
        f"reconcile {scenario['deal']}",
    )
    if memories:
        print(f"Retrieved {len(memories)} memories from RevMem:")
        for m in memories:
            print(f"  - {m.get('content', '')[:100]}")
    else:
        print("No memories available (cold start)")

    # Build prompt based on session type
    if scenario["prompt_style"] == "cold_start":
        prompt = build_cold_start_prompt(contract, crm)
        agents_md = AGENTS_MD  # basic persona, no special rules
    else:
        prompt = build_reconciliation_prompt(contract, crm, policy, memories, tier)
        agents_md = AGENTS_MD

    # Generate tier-scoped SKILL.md
    skill_content = generate_skill_md(tier)

    # Build Antigravity environment
    environment = build_environment(contract, crm, policy, skill_content, agents_md)

    # Create Antigravity interaction
    print("Sending to Antigravity agent...")
    create_kwargs = {
        "agent": AGENT_MODEL,
        "input": prompt,
        "stream": stream,
    }

    if env_id:
        create_kwargs["environment"] = env_id
    else:
        create_kwargs["environment"] = environment

    if prev_interaction_id:
        create_kwargs["previous_interaction_id"] = prev_interaction_id

    if stream:
        print("\nAgent response (streaming):")
        output_parts = []
        completed_interaction = None
        in_thinking = False
        for event in client.interactions.create(**create_kwargs):
            etype = type(event).__name__
            if etype == "StepDelta":
                delta = event.delta
                if hasattr(delta, "content") and delta.content:
                    in_thinking = True
                elif hasattr(delta, "text") and delta.text:
                    if in_thinking:
                        in_thinking = False
                        print("(thinking done)\n", flush=True)
                    print(delta.text, end="", flush=True)
                    output_parts.append(delta.text)
            elif etype == "InteractionCompletedEvent":
                completed_interaction = event.interaction
            elif etype == "InteractionStatusUpdate":
                status = getattr(event, "status", "")
                if status:
                    print(f"[{status}]", end=" ", flush=True)
        print()
        output = "".join(output_parts) if output_parts else "(no text output)"
        interaction = completed_interaction
    else:
        interaction = client.interactions.create(**create_kwargs)
        output = interaction.output_text or "(no text output)"
        print(f"\nAgent response:\n{output[:1500]}\n")

    result = {
        "session_number": session_number,
        "session_id": session_id,
        "deal": scenario["deal"],
        "tier": tier,
        "reputation": agent_state["reputation_score"],
        "memories_used": len(memories),
        "agent_output": output,
        "interaction_id": interaction.id,
        "environment_id": interaction.environment_id,
    }

    # Log outcome to RevMem
    revmem_client.log_outcome(session_id, {
        "session_number": session_number,
        "agent_output": output[:500],
    })

    print(f"Expected: {scenario['expected']['description']}")
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
