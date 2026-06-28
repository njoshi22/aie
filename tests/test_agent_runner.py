from agent import runner
from agent.prompts import build_reconciliation_prompt
from agent.scenarios import SCENARIOS
from evals import behaviors
from evals.gold import build_gold


class _FakeInteractions:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return {"ok": True}


class _FakeClient:
    def __init__(self):
        self.interactions = _FakeInteractions()


class _TimingListener:
    def __init__(self):
        self.events = []

    def on_agent_api_start(self, label):
        self.events.append(("start", label))

    def on_agent_api_end(self, label, elapsed_s):
        self.events.append(("end", label, elapsed_s))


def test_interaction_create_reports_wait_timing():
    client = _FakeClient()
    listener = _TimingListener()

    result = runner._create_interaction(
        client,
        {"agent": "model", "input": "prompt"},
        "initial response",
        listener,
        debug=False,
    )

    assert result == {"ok": True}
    assert client.interactions.calls == [{"agent": "model", "input": "prompt"}]
    assert listener.events[0] == ("start", "initial response")
    assert listener.events[1][0:2] == ("end", "initial response")
    assert listener.events[1][2] >= 0


def test_session_one_completion_payload_seeds_reviewer_lesson():
    payload = runner._completion_payload(
        {"accuracy": 0.0},
        memories_used=[],
        memories_created=[],
        scenario=SCENARIOS[1],
    )

    assert payload["lesson"]["content"].startswith("TCV parity is insufficient")
    assert payload["lesson"]["metadata"]["source"] == "session_1_reviewer_correction"


def test_approval_requests_follow_caught_material_decisions():
    requests = runner._approval_requests_for_caught_material(
        "globex",
        behaviors.modeled("globex_learned"),
        build_gold("globex"),
    )

    assert [r["field"] for r in requests] == ["annual_schedule_usd", "discount_pct"]
    assert {r["change_type"] for r in requests} == {
        "schedule_change",
        "discount_over_authority",
    }


def test_prompt_uses_prefetched_memories_without_forcing_tool_call():
    prompt = build_reconciliation_prompt(
        {"deal_id": "acme"},
        {"deal_id": "acme"},
        {"rules": []},
        [{"content": "Always compare annual schedules."}],
        "observer",
    )

    assert "RELEVANT LESSONS FROM PAST RECONCILIATIONS" in prompt
    assert "do not call retrieve_context unless the context is missing" in prompt
    assert "classify sub-$1 rounding differences as immaterial" in prompt
