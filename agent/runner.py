"""
Main agent runner — executes one reconciliation session via Antigravity.
Usage: source .venv/bin/activate && GEMINI_API_KEY=... python -m agent.runner --session 1
"""
import os
import json
import argparse
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from dotenv import load_dotenv
load_dotenv()

from google import genai

from agent.templates.agents_md import AGENTS_MD
from agent.templates.skill_md import generate_skill_md
from agent.prompts import build_reconciliation_prompt, build_cold_start_prompt
from agent.scenarios import SCENARIOS
from agent import revmem_client
from agent.tools import get_tools_for_tier
from evals import behaviors
from evals.gold import GoldItem, build_gold
from evals.grade import grade

DATA_DIR = Path(__file__).parent / "data"
AGENT_MODEL = "antigravity-preview-05-2026"
AGENT_NAME = "RevOps Finance Agent"  # matches Person B's seed; resolved get-or-create by name
APPROVAL_ACTIONS = {"escalate", "flag"}


class RunnerListener(Protocol):
    """Callback interface for live rendering of agent sessions."""

    def on_session_start(self, session_number: int, deal: str, tier: str, reputation: float, task: str) -> None: ...
    def on_tool_call(self, name: str, arguments: dict) -> None: ...
    def on_tool_result(self, name: str, result: dict) -> None: ...
    def on_memory_retrieved(self, memories: list[dict]) -> None: ...
    def on_agent_response(self, text: str) -> None: ...
    def on_approval_needed(self, approval: dict) -> None: ...
    def on_graded(self, scorecard: object, graded_from_output: bool) -> None: ...
    def on_session_end(self, result: dict) -> None: ...
    def on_agent_api_start(self, label: str) -> None: ...
    def on_agent_api_end(self, label: str, elapsed_s: float) -> None: ...
    def on_tool_timing(self, name: str, elapsed_s: float) -> None: ...


class _PrintListener:
    """Default listener — plain print output (original behavior)."""

    def on_session_start(self, session_number, deal, tier, reputation, task):
        print(f"\n{'='*60}")
        print(f"SESSION {session_number}")
        print(f"Deal: {deal.upper()} | Tier: {tier.upper()} | Rep: {reputation}")
        print(f"Task: {task}")
        print(f"{'='*60}\n")

    def on_tool_call(self, name, arguments):
        print(f"  [tool] {name}({json.dumps(arguments)})")

    def on_tool_result(self, name, result):
        pass

    def on_memory_retrieved(self, memories):
        if memories:
            for m in memories:
                print(f"    memory: {m.get('content', '')[:80]}")
        else:
            print("    (no memories found)")

    def on_agent_response(self, text):
        print(f"\nAgent response:\n{text[:1500]}\n")

    def on_approval_needed(self, approval):
        link = approval.get("approval_link", "")
        route = approval.get("route_to", "unknown")
        print(f"  Routed to {route}: {link}")

    def on_graded(self, scorecard, graded_from_output):
        source = "agent output" if graded_from_output else "modeled fallback"
        print(f"\nGraded outcome ({source}): {json.dumps(scorecard.outcome)}")
        for note in scorecard.notes:
            print(f"  - {note}")

    def on_session_end(self, result):
        print(f"Expected (designed): {SCENARIOS[result['session_number']]['expected']['description']}")
        print(f"Environment ID: {result.get('environment_id', 'n/a')}")

    def on_agent_api_start(self, label):
        print(f"  [wait] hosted agent API: {label}...")

    def on_agent_api_end(self, label, elapsed_s):
        print(f"  [timing] hosted agent API: {label} took {elapsed_s:.1f}s")

    def on_tool_timing(self, name, elapsed_s):
        print(f"  [timing] {name} took {elapsed_s:.1f}s")


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


_ENV_FILES: dict[str, str] = {}


def _debug(enabled: bool, message: str) -> None:
    if enabled:
        print(message, flush=True)


def _notify(listener: RunnerListener, method: str, *args) -> None:
    callback = getattr(listener, method, None)
    if callback:
        callback(*args)


def _create_interaction(client, kwargs: dict, label: str, listener: RunnerListener, debug: bool):
    _notify(listener, "on_agent_api_start", label)
    started = time.perf_counter()
    try:
        return client.interactions.create(**kwargs)
    finally:
        elapsed = time.perf_counter() - started
        _notify(listener, "on_agent_api_end", label, elapsed)
        _debug(debug, f"[timing] hosted agent API {label}: {elapsed:.2f}s")


def _memory_query_for_scenario(scenario: dict) -> str:
    return (
        f"{scenario['deal']} reconciliation lessons payment schedule "
        "ramp rounding discount policy"
    )


def _completion_payload(
    outcome: dict,
    memories_used: list[str],
    memories_created: list[str],
    scenario: dict,
) -> dict:
    payload = {
        **outcome,
        "memories_used": memories_used,
        "memories_created": memories_created,
    }
    lesson = scenario.get("reviewer_lesson")
    if lesson:
        payload["lesson"] = lesson
    return payload


def _approval_requests_for_caught_material(
    deal: str,
    decisions: list[behaviors.Decision],
    gold: list[GoldItem],
) -> list[dict]:
    by_field = {d.field: d for d in decisions}
    requests = []
    for item in gold:
        decision = by_field.get(item.field)
        if not item.material or decision is None or decision.action not in APPROVAL_ACTIONS:
            continue
        summary = (
            f"{item.field}: contract={item.contract!r}, CRM={item.crm!r}; "
            f"route to {item.expected_route or 'approver'}"
        )
        requests.append({
            "deal_id": deal,
            "amount_usd": float(item.diff_usd),
            "change_type": item.change_type or "value_change",
            "summary": summary,
            "field": item.field,
        })
    return requests


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

    if name == "read_file":
        path = arguments.get("path", "")
        for key, content in _ENV_FILES.items():
            if path.endswith(key) or key.endswith(path.lstrip("/.")) or path in key:
                return {"content": content}
        return {"error": f"File not found: {path}"}

    if name == "list_files":
        path = arguments.get("path", ".")
        matches = [k for k in _ENV_FILES if k.startswith(path.rstrip("/")) or path == "."]
        return {"files": matches}

    return {"error": f"Unknown tool: {name}", "skipped": True}


def run_session(
    session_number: int,
    env_id: str | None = None,
    prev_interaction_id: str | None = None,
    stream: bool = True,
    listener: RunnerListener | None = None,
    agent_name: str = AGENT_NAME,
    debug: bool = False,
) -> dict:
    listener = listener or _PrintListener()
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    scenario = SCENARIOS[session_number]

    contract, crm, policy = load_deal_data(scenario["deal"])

    agent_state = revmem_client.ensure_agent(agent_name)
    agent_id = agent_state["id"]
    tier = agent_state["permission_tier"]

    listener.on_session_start(session_number, scenario["deal"], tier, agent_state["reputation_score"], scenario["task"])

    session = revmem_client.start_session(agent_id, scenario["task"])
    session_id = session["id"]
    memories_used = 0
    memories_used_ids: list[str] = []
    prefetched_memories: list[dict] = []

    if scenario["prompt_style"] != "cold_start":
        query = _memory_query_for_scenario(scenario)
        listener.on_tool_call("retrieve_context", {"query": query, "mode": "prefetch"})
        tool_started = time.perf_counter()
        prefetched_memories = revmem_client.retrieve_context(agent_id, query)
        _notify(listener, "on_tool_timing", "retrieve_context", time.perf_counter() - tool_started)
        listener.on_memory_retrieved(prefetched_memories)
        memories_used = len(prefetched_memories)
        memories_used_ids.extend(
            str(m["id"]) for m in prefetched_memories
            if isinstance(m, dict) and m.get("id")
        )

    if scenario["prompt_style"] == "cold_start":
        prompt = build_cold_start_prompt(contract, crm)
    else:
        prompt = build_reconciliation_prompt(contract, crm, policy, prefetched_memories, tier)

    skill_content = generate_skill_md(tier)
    tools = get_tools_for_tier(tier)
    environment = build_environment(contract, crm, policy, skill_content, AGENTS_MD)

    _ENV_FILES.clear()
    for src in environment["sources"]:
        _ENV_FILES[src["target"]] = src["content"]

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

    interaction = _create_interaction(client, create_kwargs, "initial response", listener, debug)
    tool_calls_made = []

    max_tool_rounds = 3
    for round_num in range(max_tool_rounds):
        _debug(debug, f"\n[debug] round {round_num}: interaction.status={interaction.status}")
        if interaction.status != "requires_action":
            break

        all_steps = [s.to_dict() for s in interaction.steps]
        _debug(debug, f"[debug] all steps ({len(all_steps)}):")
        for s in all_steps:
            _debug(debug, f"  type={s.get('type')}  name={s.get('name', '-')}  id={s.get('id', '-')[:12]}")

        resolved_tools = {s.get("name") for s in all_steps if s.get("type") == "function_result"}
        fc_steps = [s for s in all_steps if s.get("type") == "function_call" and s.get("name") not in resolved_tools]
        _debug(debug, f"[debug] fc_steps (unresolved): {[s['name'] for s in fc_steps]} | already resolved: {resolved_tools}")
        if not fc_steps:
            break

        results = []
        for fc in fc_steps:
            tool_name = fc["name"]
            tool_args = fc.get("arguments", {})
            listener.on_tool_call(tool_name, tool_args)
            tool_calls_made.append(tool_name)

            tool_started = time.perf_counter()
            tool_result = _execute_tool(tool_name, tool_args, agent_id, session_id)
            _notify(listener, "on_tool_timing", tool_name, time.perf_counter() - tool_started)
            listener.on_tool_result(tool_name, tool_result)

            if tool_name == "retrieve_context":
                mems = tool_result.get("memories", [])
                memories_used += len(mems)
                for m in mems:
                    if isinstance(m, dict) and m.get("id") and str(m["id"]) not in memories_used_ids:
                        memories_used_ids.append(str(m["id"]))
                listener.on_memory_retrieved(mems)

            if tool_name == "route_for_approval" and tool_result.get("approval_id"):
                listener.on_approval_needed(tool_result)

            results.append({
                "type": "function_result",
                "call_id": fc["id"],
                "name": tool_name,
                "result": tool_result,
            })

        _debug(debug, f"[debug] sending {len(results)} results: {[r['name'] for r in results]}")
        _debug(debug, f"[debug] calling interactions.create with prev_id={interaction.id[:12]}...")
        interaction = _create_interaction(
            client,
            {
                "agent": AGENT_MODEL,
                "previous_interaction_id": interaction.id,
                "environment": interaction.environment_id,
                "input": results,
            },
            "after tool results",
            listener,
            debug,
        )
        _debug(debug, f"[debug] got response: status={interaction.status}")

    output = interaction.output_text or "(no text output)"
    listener.on_agent_response(output)

    decisions = behaviors.decisions_from_output(output)
    graded_from_output = bool(decisions)
    if not decisions:
        step = f"{scenario['deal']}_{'cold' if scenario['prompt_style'] == 'cold_start' else 'learned'}"
        try:
            decisions = behaviors.modeled(step)
        except KeyError:
            decisions = []
    gold = build_gold(scenario["deal"])
    scorecard = grade(scenario["deal"], decisions, gold)
    outcome = scorecard.outcome

    fallback_approvals = []
    if "route_for_approval" not in tool_calls_made:
        for req in _approval_requests_for_caught_material(scenario["deal"], decisions, gold):
            approval = revmem_client.route_for_approval(
                req["deal_id"],
                req["amount_usd"],
                req["change_type"],
                summary=req["summary"],
            )
            if isinstance(approval, dict) and approval.get("approval_id"):
                approval.setdefault("summary", req["summary"])
                approval.setdefault("field", req["field"])
                fallback_approvals.append(approval)
                listener.on_approval_needed(approval)

    result = {
        "session_number": session_number,
        "session_id": session_id,
        "agent_id": agent_id,
        "deal": scenario["deal"],
        "tier": tier,
        "reputation": agent_state["reputation_score"],
        "starting_tier": tier,
        "starting_reputation": agent_state["reputation_score"],
        "memories_used": memories_used,
        "memories_used_ids": memories_used_ids,
        "approvals_routed": fallback_approvals,
        "agent_output": output,
        "interaction_id": interaction.id,
        "environment_id": interaction.environment_id,
        "outcome": outcome,
        "graded_from_output": graded_from_output,
    }

    completion = revmem_client.complete_session(
        session_id,
        _completion_payload(outcome, memories_used_ids, [], scenario),
    )
    if isinstance(completion, dict) and isinstance(completion.get("agent"), dict):
        agent_after = completion["agent"]
        result["reputation"] = agent_after.get("reputation_score", result["reputation"])
        result["tier"] = agent_after.get("permission_tier", result["tier"])
    listener.on_graded(scorecard, graded_from_output)
    listener.on_session_end(result)

    return result


def main():
    parser = argparse.ArgumentParser(description="Run a RevMem reconciliation session")
    parser.add_argument("--session", type=int, required=True, choices=[1, 2, 3])
    parser.add_argument("--env-id", type=str, default=None)
    parser.add_argument("--prev-interaction", type=str, default=None)
    parser.add_argument("--no-stream", action="store_true", help="Disable streaming output")
    parser.add_argument("--agent-name", default=AGENT_NAME, help="RevMem agent name to get or create")
    parser.add_argument("--debug", action="store_true", help="Print Interactions API step debugging")
    args = parser.parse_args()

    result = run_session(
        args.session,
        args.env_id,
        args.prev_interaction,
        stream=not args.no_stream,
        agent_name=args.agent_name,
        debug=args.debug,
    )
    print(f"\n--- Session {args.session} complete ---")
    print(json.dumps({k: v for k, v in result.items() if k != "agent_output"}, indent=2))


if __name__ == "__main__":
    main()
