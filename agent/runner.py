"""
Main agent runner — executes one reconciliation session via Antigravity.
Usage: source .venv/bin/activate && GEMINI_API_KEY=... python -m agent.runner --session 1
"""
import argparse
import json
import os
from pathlib import Path
from typing import Any, Protocol, TypedDict, cast

from dotenv import load_dotenv
from google import genai

from agent.templates.agents_md import AGENTS_MD
from agent.templates.skill_md import generate_skill_md
from agent.prompts import build_reconciliation_prompt, build_cold_start_prompt
from agent.scenarios import SCENARIOS
from agent.tool_types import JsonObject, ToolCallRecord
from agent.tools import get_tools_for_tier
from evals import behaviors
from evals.gold import GoldItem, build_gold
from evals.grade import Decision, grade

load_dotenv()

from agent import revmem_client  # noqa: E402

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
AGENT_MODEL = "antigravity-preview-05-2026"
AGENT_NAME = "RevOps Finance Agent"  # matches Person B's seed; resolved get-or-create by name


class ScenarioExpected(TypedDict):
    material_caught: int
    false_escalations: int
    accuracy: float
    description: str


class Scenario(TypedDict):
    deal: str
    task: str
    prompt_style: str
    expected: ScenarioExpected


class RunnerListener(Protocol):
    """Callback interface for live rendering of agent sessions."""

    def on_session_start(self, session_number: int, deal: str, tier: str, reputation: float, task: str) -> None: ...
    def on_tool_call(self, name: str, arguments: JsonObject) -> None: ...
    def on_tool_result(self, name: str, result: JsonObject) -> None: ...
    def on_memory_retrieved(self, memories: list[JsonObject]) -> None: ...
    def on_agent_response(self, text: str) -> None: ...
    def on_approval_needed(self, approval: JsonObject) -> None: ...
    def on_graded(self, scorecard: object, graded_from_output: bool) -> None: ...
    def on_session_end(self, result: JsonObject) -> None: ...


class _PrintListener:
    """Default listener — plain print output (original behavior)."""

    def on_session_start(self, session_number: int, deal: str, tier: str, reputation: float, task: str) -> None:
        print(f"\n{'='*60}")
        print(f"SESSION {session_number}")
        print(f"Deal: {deal.upper()} | Tier: {tier.upper()} | Rep: {reputation}")
        print(f"Task: {task}")
        print(f"{'='*60}\n")

    def on_tool_call(self, name: str, arguments: JsonObject) -> None:
        print(f"  [tool] {name}({json.dumps(arguments)})")

    def on_tool_result(self, name: str, result: JsonObject) -> None:
        pass

    def on_memory_retrieved(self, memories: list[JsonObject]) -> None:
        if memories:
            for m in memories:
                print(f"    memory: {m.get('content', '')[:80]}")
        else:
            print("    (no memories found)")

    def on_agent_response(self, text: str) -> None:
        print(f"\nAgent response:\n{text[:1500]}\n")

    def on_approval_needed(self, approval: JsonObject) -> None:
        link = approval.get("approval_link", "")
        route = approval.get("route_to", "unknown")
        print(f"  Routed to {route}: {link}")

    def on_graded(self, scorecard: object, graded_from_output: bool) -> None:
        source = "agent output" if graded_from_output else "modeled fallback"
        outcome = getattr(scorecard, "outcome")
        notes = cast(list[str], getattr(scorecard, "notes"))
        print(f"\nGraded outcome ({source}): {json.dumps(outcome)}")
        for note in notes:
            print(f"  - {note}")

    def on_session_end(self, result: JsonObject) -> None:
        session_number = cast(int, result["session_number"])
        scenario = cast(Scenario, SCENARIOS[session_number])
        print(f"Expected (designed): {scenario['expected']['description']}")
        print(f"Environment ID: {result.get('environment_id', 'n/a')}")


def load_deal_data(deal_name: str) -> tuple[JsonObject, JsonObject, JsonObject]:
    contracts = json.loads((DATA_DIR / "contracts.json").read_text())
    crm_records = json.loads((DATA_DIR / "salesforce.json").read_text())
    policy = json.loads((DATA_DIR / "policy.json").read_text())
    return contracts[deal_name], crm_records[deal_name], policy


def build_environment(
    contract: JsonObject,
    crm: JsonObject,
    policy: JsonObject,
    skill_content: str,
    agents_md: str,
) -> JsonObject:
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


_ENV_FILES: dict[str, str] = {}


def _execute_tool(name: str, arguments: JsonObject, agent_id: str, session_id: str) -> JsonObject:
    """Execute a tool call against RevMem and return the result as a dict."""
    if name == "get_contract":
        return revmem_client.get_contract(str(arguments.get("deal_id", "")))

    if name == "get_crm_record":
        return revmem_client.get_crm_record(str(arguments.get("deal_id", "")))

    if name == "retrieve_context":
        bundle = revmem_client.retrieve_context(
            agent_id, arguments.get("query", ""),
        )
        memories = bundle.get("memories", [])
        return {"memories": memories, "policy": bundle.get("policy", []), "count": len(memories)}

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
            str(arguments.get("deal_id", "")),
            float(arguments.get("amount_usd", 0)),
            str(arguments.get("change_type", "")),
            summary=arguments.get("summary", ""),
        )
        return result

    if name == "get_approval_status":
        return revmem_client.get_approval_status(str(arguments.get("approval_id", "")))

    if name == "write_crm":
        fields = arguments.get("fields", {})
        discrepancy = arguments.get("discrepancy", {})
        return revmem_client.write_crm(
            agent_id=agent_id,
            deal_id=str(arguments.get("deal_id", "")),
            fields=cast(JsonObject, fields) if isinstance(fields, dict) else {},
            discrepancy=cast(JsonObject, discrepancy) if isinstance(discrepancy, dict) else {},
            approval_id=cast(str | None, arguments.get("approval_id")),
        )

    if name == "read_file":
        path = str(arguments.get("path", ""))
        for key, content in _ENV_FILES.items():
            if path.endswith(key) or key.endswith(path.lstrip("/.")) or path in key:
                return {"content": content}
        return {"error": f"File not found: {path}"}

    if name == "list_files":
        path = str(arguments.get("path", "."))
        matches = [key for key in _ENV_FILES if key.startswith(path.rstrip("/")) or path == "."]
        return {"files": matches}

    return {"error": f"Unknown tool: {name}", "skipped": True}


def _route_evidence_by_change_type(tool_calls: list[ToolCallRecord]) -> dict[tuple[str, str], JsonObject]:
    evidence: dict[tuple[str, str], JsonObject] = {}
    for call in tool_calls:
        if call["name"] != "route_for_approval":
            continue
        deal_id = str(call["arguments"].get("deal_id", ""))
        change_type = str(call["arguments"].get("change_type", ""))
        if deal_id and change_type and call["result"].get("approval_id"):
            evidence[(deal_id, change_type)] = call["result"]
    return evidence


def audit_decisions_for_tool_evidence(
    deal: str,
    decisions: list[Decision],
    gold: list[GoldItem],
    tool_calls: list[ToolCallRecord],
) -> tuple[list[Decision], list[str]]:
    evidence = _route_evidence_by_change_type(tool_calls)
    gold_by_field = {item.field: item for item in gold}
    audited: list[Decision] = []
    notes: list[str] = []

    for decision in decisions:
        item = gold_by_field.get(decision.field)
        if item is None or not item.material:
            audited.append(decision)
            continue

        change_type = item.change_type or ""
        route = evidence.get((deal, change_type))
        if route is None:
            audited.append(Decision(decision.field, "miss"))
            notes.append(f"{decision.field}: missing route_for_approval tool call")
            continue

        audited.append(
            Decision(
                decision.field,
                decision.action,
                route_to=str(route.get("route_to", decision.route_to or "")) or None,
            )
        )

    return audited, notes


def run_session(
    session_number: int,
    env_id: str | None = None,
    prev_interaction_id: str | None = None,
    stream: bool = True,
    listener: RunnerListener | None = None,
) -> JsonObject:
    active_listener: RunnerListener = listener if listener is not None else _PrintListener()
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    scenario = cast(Scenario, SCENARIOS[session_number])
    deal = scenario["deal"]
    task = scenario["task"]

    contract, crm, policy = load_deal_data(deal)

    agent_state = revmem_client.ensure_agent(AGENT_NAME)
    agent_id = str(agent_state["id"])
    tier = str(agent_state["permission_tier"])
    reputation = float(agent_state["reputation_score"])

    active_listener.on_session_start(session_number, deal, tier, reputation, task)

    session = revmem_client.start_session(agent_id, task)
    session_id = str(session["id"])

    if scenario["prompt_style"] == "cold_start":
        prompt = build_cold_start_prompt(contract, crm)
    else:
        prompt = build_reconciliation_prompt(contract, crm, policy, [], tier)

    skill_content = generate_skill_md(tier)
    tools = get_tools_for_tier(tier)
    environment = build_environment(contract, crm, policy, skill_content, AGENTS_MD)

    _ENV_FILES.clear()
    for src in environment["sources"]:
        _ENV_FILES[src["target"]] = src["content"]

    create_interaction = cast(Any, client.interactions.create)
    interaction = create_interaction(
        agent=AGENT_MODEL,
        input=prompt,
        tools=tools,
        environment=env_id or environment,
        previous_interaction_id=prev_interaction_id,
    )
    memories_used = 0
    tool_calls_made: list[ToolCallRecord] = []

    max_tool_rounds = 8
    for _ in range(max_tool_rounds):
        if interaction.status != "requires_action":
            break

        all_steps = [s.to_dict() for s in interaction.steps]
        resolved_tools = {s.get("name") for s in all_steps if s.get("type") == "function_result"}
        fc_steps = [s for s in all_steps if s.get("type") == "function_call" and s.get("name") not in resolved_tools]
        if not fc_steps:
            break

        results = []
        for fc in fc_steps:
            tool_name = fc["name"]
            tool_args = fc.get("arguments", {})
            active_listener.on_tool_call(tool_name, tool_args)

            tool_result = _execute_tool(tool_name, tool_args, agent_id, session_id)
            tool_calls_made.append({
                "name": tool_name,
                "arguments": tool_args,
                "result": tool_result,
                "source": "model",
            })
            active_listener.on_tool_result(tool_name, tool_result)

            if tool_name == "retrieve_context":
                mems = tool_result.get("memories", [])
                memories_used += len(mems)
                active_listener.on_memory_retrieved(mems)

            if tool_name == "route_for_approval" and tool_result.get("approval_id"):
                active_listener.on_approval_needed(tool_result)

            results.append({
                "type": "function_result",
                "call_id": fc["id"],
                "name": tool_name,
                "result": tool_result,
            })

        interaction = create_interaction(
            agent=AGENT_MODEL,
            previous_interaction_id=interaction.id,
            environment=interaction.environment_id,
            input=results,
        )

    output = interaction.output_text or "(no text output)"
    active_listener.on_agent_response(output)

    decisions = behaviors.decisions_from_output(output)
    graded_from_output = bool(decisions)
    if not decisions:
        step = f"{scenario['deal']}_{'cold' if scenario['prompt_style'] == 'cold_start' else 'learned'}"
        try:
            decisions = behaviors.modeled(step)
        except KeyError:
            decisions = []
    gold = build_gold(deal)
    audited_decisions, audit_notes = audit_decisions_for_tool_evidence(
        deal,
        decisions,
        gold,
        tool_calls_made,
    )
    scorecard = grade(deal, audited_decisions, gold)
    scorecard.notes.extend(audit_notes)
    outcome = scorecard.outcome

    result = {
        "session_number": session_number,
        "session_id": session_id,
        "agent_id": agent_id,
        "deal": deal,
        "tier": tier,
        "reputation": reputation,
        "memories_used": memories_used,
        "agent_output": output,
        "interaction_id": interaction.id,
        "environment_id": interaction.environment_id,
        "tool_calls": tool_calls_made,
        "audit_notes": audit_notes,
        "outcome": outcome,
        "graded_from_output": graded_from_output,
    }

    revmem_client.complete_session(session_id, outcome)
    active_listener.on_graded(scorecard, graded_from_output)
    active_listener.on_session_end(result)

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
