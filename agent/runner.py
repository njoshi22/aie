"""
Main agent runner — executes one reconciliation session via Antigravity.
Usage: source .venv/bin/activate && GEMINI_API_KEY=... python -m agent.runner --session 1
"""
import argparse
import json
import os
import time
from pathlib import Path
from typing import Any, NotRequired, Protocol, TypedDict, cast

from dotenv import load_dotenv
from google import genai

from agent.templates.agents_md import AGENTS_MD
from agent.templates.skill_md import generate_skill_md
from agent.prompts import build_reconciliation_prompt, build_feedback_prompt
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
AGENT_API_TIMEOUT_S = 90.0  # per-HTTP-request cap for create/get (each is fast in background mode)
AGENT_TURN_DEADLINE_S = 300.0  # max wall-clock to await one background agent turn before failing loud
AGENT_POLL_INTERVAL_S = 3.0  # cadence for polling a backgrounded interaction's status


class ScenarioExpected(TypedDict):
    material_caught: int
    false_escalations: int
    accuracy: float
    description: str


class ReviewerLesson(TypedDict):
    type: str
    content: str
    metadata: JsonObject


class Scenario(TypedDict):
    deal: str
    task: str
    prompt_style: str
    expected: ScenarioExpected
    reviewer_lesson: NotRequired[ReviewerLesson]


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
    def on_agent_api_start(self, label: str) -> None: ...
    def on_agent_api_end(self, label: str, elapsed_s: float) -> None: ...
    def on_tool_timing(self, name: str, elapsed_s: float) -> None: ...


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

    def on_agent_api_start(self, label):
        print(f"  [wait] hosted agent API: {label}...")

    def on_agent_api_end(self, label, elapsed_s):
        print(f"  [timing] hosted agent API: {label} took {elapsed_s:.1f}s")

    def on_tool_timing(self, name, elapsed_s):
        print(f"  [timing] {name} took {elapsed_s:.1f}s")


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


def _debug(enabled: bool, message: str) -> None:
    if enabled:
        print(message, flush=True)


def _notify(listener: RunnerListener, method: str, *args) -> None:
    callback = getattr(listener, method, None)
    if callback:
        callback(*args)


def _await_interaction(client, interaction, debug: bool):
    """Poll a backgrounded interaction until it leaves ``in_progress``.

    Hosted-agent turns can run for tens of seconds; a synchronous blocking
    ``create`` holds the connection for the whole turn and stalls. Background
    mode returns immediately, so we poll ``get`` instead, failing loud if the
    turn is still running past the deadline.
    """
    deadline = time.perf_counter() + AGENT_TURN_DEADLINE_S
    while getattr(interaction, "status", None) == "in_progress":
        if time.perf_counter() > deadline:
            raise TimeoutError(
                f"hosted agent turn {getattr(interaction, 'id', '?')} still in_progress "
                f"after {AGENT_TURN_DEADLINE_S:.0f}s"
            )
        time.sleep(AGENT_POLL_INTERVAL_S)
        interaction = client.interactions.get(interaction.id, timeout=AGENT_API_TIMEOUT_S)
        _debug(debug, f"[poll] {str(interaction.id)[:14]} status={interaction.status}")
    return interaction


def _create_interaction(client, kwargs: dict, label: str, listener: RunnerListener, debug: bool):
    _notify(listener, "on_agent_api_start", label)
    started = time.perf_counter()
    try:
        interaction = client.interactions.create(background=True, timeout=AGENT_API_TIMEOUT_S, **kwargs)
        return _await_interaction(client, interaction, debug)
    finally:
        elapsed = time.perf_counter() - started
        _notify(listener, "on_agent_api_end", label, elapsed)
        _debug(debug, f"[timing] hosted agent API {label}: {elapsed:.2f}s")


def _memory_query_for_scenario(scenario: Scenario) -> str:
    return (
        f"{scenario['deal']} reconciliation lessons payment schedule "
        "ramp rounding discount policy"
    )


def _completion_payload(
    outcome: JsonObject,
    memories_used: list[str],
    memories_created: list[str],
    scenario: Scenario,
) -> JsonObject:
    payload = {
        **outcome,
        "memories_used": memories_used,
        "memories_created": memories_created,
    }
    lesson = scenario.get("reviewer_lesson")
    if lesson:
        payload["lesson"] = lesson
    return payload


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
        return revmem_client.get_approval_status(str(arguments.get("approval_request_id", "")))

    if name == "write_crm":
        fields = arguments.get("fields", {})
        discrepancy = arguments.get("discrepancy", {})
        return revmem_client.write_crm(
            agent_id=agent_id,
            deal_id=str(arguments.get("deal_id", "")),
            fields=cast(JsonObject, fields) if isinstance(fields, dict) else {},
            discrepancy=cast(JsonObject, discrepancy) if isinstance(discrepancy, dict) else {},
            approval_request_id=cast(str | None, arguments.get("approval_request_id")),
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


def _is_approval_evidence(tool_name: str, result: JsonObject) -> bool:
    if tool_name == "route_for_approval":
        return bool(result.get("approval_request_id") or result.get("approval_id"))
    return bool(result.get("approval_required") and result.get("approval_request_id"))


def _approval_evidence_by_change_type(
    tool_calls: list[ToolCallRecord],
) -> dict[tuple[str, str], tuple[JsonObject, str]]:
    evidence: dict[tuple[str, str], tuple[JsonObject, str]] = {}
    for call in tool_calls:
        arguments = call["arguments"]
        result = call["result"]
        deal_id = ""
        change_type = ""
        if call["name"] == "route_for_approval":
            deal_id = str(arguments.get("deal_id", ""))
            change_type = str(arguments.get("change_type", ""))
        elif result.get("approval_required") and result.get("approval_request_id"):
            discrepancy = arguments.get("discrepancy", {})
            if isinstance(discrepancy, dict):
                deal_id = str(arguments.get("deal_id") or discrepancy.get("deal_id") or "")
                change_type = str(discrepancy.get("change_type", ""))
        if deal_id and change_type and _is_approval_evidence(call["name"], result):
            evidence[(deal_id, change_type)] = (call["result"], str(call.get("source", "model")))
    return evidence


def _approval_payload(arguments: JsonObject, result: JsonObject, source: str) -> JsonObject:
    payload: JsonObject = dict(result)
    for key in ("deal_id", "amount_usd", "change_type", "summary"):
        if key in arguments:
            payload[key] = arguments[key]
    payload["source"] = source
    return payload


def audit_decisions_for_tool_evidence(
    deal: str,
    decisions: list[Decision],
    gold: list[GoldItem],
    tool_calls: list[ToolCallRecord],
) -> tuple[list[Decision], list[str]]:
    evidence = _approval_evidence_by_change_type(tool_calls)
    gold_by_field = {item.field: item for item in gold}
    audited: list[Decision] = []
    notes: list[str] = []

    for decision in decisions:
        item = gold_by_field.get(decision.field)
        if item is None or not item.material:
            audited.append(decision)
            continue

        change_type = item.change_type or ""
        route_entry = evidence.get((deal, change_type))
        if route_entry is None:
            audited.append(Decision(decision.field, "miss"))
            notes.append(f"{decision.field}: missing approval request")
            continue

        route = route_entry[0]
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
    listener: RunnerListener | None = None,
    agent_name: str = AGENT_NAME,
    debug: bool = False,
) -> JsonObject:
    active_listener: RunnerListener = listener if listener is not None else _PrintListener()
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    scenario = cast(Scenario, SCENARIOS[session_number])
    deal = scenario["deal"]
    task = scenario["task"]

    contract, crm, policy = load_deal_data(deal)

    agent_state = revmem_client.ensure_agent(agent_name)
    agent_id = str(agent_state["id"])
    tier = str(agent_state["permission_tier"])
    reputation = float(agent_state["reputation_score"])

    active_listener.on_session_start(session_number, deal, tier, reputation, task)

    session = revmem_client.start_session(agent_id, task)
    session_id = str(session["id"])
    memories_used = 0
    memories_used_ids: list[str] = []
    prefetched_memories: list[dict] = []

    query = _memory_query_for_scenario(scenario)
    _notify(active_listener, "on_tool_call", "retrieve_context", {"query": query, "mode": "prefetch"})
    tool_started = time.perf_counter()
    bundle = revmem_client.retrieve_context(agent_id, query)
    prefetched_memories = bundle.get("memories", []) if isinstance(bundle, dict) else bundle
    _notify(active_listener, "on_tool_timing", "retrieve_context", time.perf_counter() - tool_started)
    _notify(active_listener, "on_memory_retrieved", prefetched_memories)
    memories_used = len(prefetched_memories)
    memories_used_ids.extend(
        str(m["id"]) for m in prefetched_memories
        if isinstance(m, dict) and m.get("id")
    )

    prompt = build_reconciliation_prompt(contract, crm, policy, prefetched_memories, tier)

    skill_content = generate_skill_md(tier)
    tools = get_tools_for_tier(tier)
    environment = build_environment(contract, crm, policy, skill_content, AGENTS_MD)

    _ENV_FILES.clear()
    for src in environment["sources"]:
        _ENV_FILES[src["target"]] = src["content"]

    create_kwargs: dict[str, Any] = {
        "agent": AGENT_MODEL,
        "input": prompt,
        "tools": tools,
        "environment": env_id or environment,
    }

    if prev_interaction_id:
        create_kwargs["previous_interaction_id"] = prev_interaction_id

    interaction = _create_interaction(client, create_kwargs, "initial response", active_listener, debug)
    tool_calls_made: list[ToolCallRecord] = []

    max_tool_rounds = 8
    for round_num in range(max_tool_rounds):
        _debug(debug, f"\n[debug] round {round_num}: interaction.status={interaction.status}")
        if interaction.status != "requires_action":
            break

        all_steps = [s.to_dict() for s in interaction.steps]
        _debug(debug, f"[debug] all steps ({len(all_steps)}):")
        for s in all_steps:
            _debug(debug, f"  type={s.get('type')}  name={s.get('name', '-')}  id={s.get('id', '-')[:12]}")

        resolved_call_ids = {s.get("call_id") for s in all_steps if s.get("type") == "function_result"}
        fc_steps = [s for s in all_steps if s.get("type") == "function_call" and s.get("id") not in resolved_call_ids]
        _debug(debug, f"[debug] fc_steps (unresolved): {[s['name'] for s in fc_steps]} | already resolved call_ids: {resolved_call_ids}")
        if not fc_steps:
            break

        results = []
        for fc in fc_steps:
            tool_name = fc["name"]
            raw_tool_args = fc.get("arguments", {})
            tool_args = raw_tool_args if isinstance(raw_tool_args, dict) else {}
            _notify(active_listener, "on_tool_call", tool_name, tool_args)

            tool_started = time.perf_counter()
            tool_result = _execute_tool(tool_name, tool_args, agent_id, session_id)
            _notify(active_listener, "on_tool_timing", tool_name, time.perf_counter() - tool_started)

            tool_calls_made.append({
                "name": tool_name,
                "arguments": tool_args,
                "result": tool_result,
                "source": "model",
            })
            _notify(active_listener, "on_tool_result", tool_name, tool_result)

            if tool_name == "retrieve_context":
                mems = tool_result.get("memories", [])
                memories_used += len(mems)
                for m in mems:
                    if isinstance(m, dict) and m.get("id") and str(m["id"]) not in memories_used_ids:
                        memories_used_ids.append(str(m["id"]))
                _notify(active_listener, "on_memory_retrieved", mems)

            if _is_approval_evidence(tool_name, tool_result):
                _notify(active_listener, "on_approval_needed", _approval_payload(tool_args, tool_result, "model"))

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
            active_listener,
            debug,
        )
        _debug(debug, f"[debug] got response: status={interaction.status}")

    output = interaction.output_text or "(no text output)"
    _notify(active_listener, "on_agent_response", output)

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

    approvals_routed = [
        _approval_payload(call["arguments"], call["result"], str(call.get("source", "model")))
        for call in tool_calls_made
        if _is_approval_evidence(call["name"], call["result"])
    ]

    result: JsonObject = {
        "session_number": session_number,
        "session_id": session_id,
        "agent_id": agent_id,
        "deal": deal,
        "tier": tier,
        "reputation": reputation,
        "starting_tier": tier,
        "starting_reputation": reputation,
        "memories_used": memories_used,
        "memories_used_ids": memories_used_ids,
        "approvals_routed": approvals_routed,
        "agent_output": output,
        "interaction_id": interaction.id,
        "environment_id": interaction.environment_id,
        "tool_calls": tool_calls_made,
        "audit_notes": audit_notes,
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
    _notify(active_listener, "on_graded", scorecard, graded_from_output)
    _notify(active_listener, "on_session_end", result)

    return result


def send_feedback(
    feedback_text: str,
    env_id: str,
    prev_interaction_id: str,
    agent_id: str,
    session_id: str,
    listener: RunnerListener | None = None,
    debug: bool = False,
) -> JsonObject:
    """Send human feedback as a new interaction in the same chain.

    The agent receives the feedback and is expected to call store_memory
    autonomously to persist the lesson.
    """
    active_listener: RunnerListener = listener if listener is not None else _PrintListener()
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    agent_state = revmem_client.get_agent(agent_id)
    tier = str(agent_state["permission_tier"])
    tools = get_tools_for_tier(tier)
    prompt = build_feedback_prompt(feedback_text)

    _ENV_FILES.clear()
    skill_content = generate_skill_md(tier)
    for target, content in [
        (".agents/AGENTS.md", AGENTS_MD),
        (".agents/skills/reconciliation/SKILL.md", skill_content),
    ]:
        _ENV_FILES[target] = content

    create_kwargs: dict[str, Any] = {
        "agent": AGENT_MODEL,
        "input": prompt,
        "tools": tools,
        "environment": env_id,
        "previous_interaction_id": prev_interaction_id,
    }

    interaction = _create_interaction(client, create_kwargs, "feedback response", active_listener, debug)
    tool_calls_made: list[ToolCallRecord] = []

    max_tool_rounds = 8
    for round_num in range(max_tool_rounds):
        if interaction.status != "requires_action":
            break

        all_steps = [s.to_dict() for s in interaction.steps]
        resolved_call_ids = {s.get("call_id") for s in all_steps if s.get("type") == "function_result"}
        fc_steps = [s for s in all_steps if s.get("type") == "function_call" and s.get("id") not in resolved_call_ids]
        if not fc_steps:
            break

        results = []
        for fc in fc_steps:
            tool_name = fc["name"]
            tool_args = fc.get("arguments", {})
            tool_args = tool_args if isinstance(tool_args, dict) else {}
            _notify(active_listener, "on_tool_call", tool_name, tool_args)

            tool_result = _execute_tool(tool_name, tool_args, agent_id, session_id)
            tool_calls_made.append({"name": tool_name, "arguments": tool_args, "result": tool_result, "source": "model"})
            _notify(active_listener, "on_tool_result", tool_name, tool_result)

            results.append({"type": "function_result", "call_id": fc["id"], "name": tool_name, "result": tool_result})

        interaction = _create_interaction(
            client,
            {"agent": AGENT_MODEL, "previous_interaction_id": interaction.id, "environment": interaction.environment_id, "input": results},
            "after feedback tools",
            active_listener,
            debug,
        )

    output = interaction.output_text or "(no text output)"
    _notify(active_listener, "on_agent_response", output)

    stored = any(c["name"] == "store_memory" for c in tool_calls_made)
    if not stored:
        fb = revmem_client.start_session(agent_id, "store-feedback-lesson")
        revmem_client.complete_session(fb["id"], {
            "accuracy": 1.0,
            "lesson": {"type": "lesson", "content": feedback_text},
        })
        stored = True
    return {
        "interaction_id": interaction.id,
        "environment_id": interaction.environment_id,
        "agent_output": output,
        "tool_calls": tool_calls_made,
        "memory_stored": stored,
    }


def main():
    parser = argparse.ArgumentParser(description="Run a RevMem reconciliation session")
    parser.add_argument("--session", type=int, required=True, choices=[1, 2, 3])
    parser.add_argument("--env-id", type=str, default=None)
    parser.add_argument("--prev-interaction", type=str, default=None)
    parser.add_argument("--agent-name", default=AGENT_NAME, help="RevMem agent name to get or create")
    parser.add_argument("--debug", action="store_true", help="Print Interactions API step debugging")
    args = parser.parse_args()

    result = run_session(
        args.session,
        args.env_id,
        args.prev_interaction,
        agent_name=args.agent_name,
        debug=args.debug,
    )
    print(f"\n--- Session {args.session} complete ---")
    print(json.dumps({k: v for k, v in result.items() if k != "agent_output"}, indent=2))


if __name__ == "__main__":
    main()
