import sys

from cli import run as cli_run


def test_beat_skips_sleep_when_delay_scale_is_zero(monkeypatch):
    calls = []
    monkeypatch.setattr(cli_run.time, "sleep", calls.append)

    cli_run._beat(0.6, delay_scale=0)
    assert calls == []

    cli_run._beat(0.6, delay_scale=0.5)
    assert calls == [0.3]


def test_fast_mode_disables_approval_wait(monkeypatch):
    monkeypatch.delenv("REVMEM_CLI_FAST", raising=False)
    assert cli_run._approval_wait_enabled(no_wait=False, fast=False) is True
    assert cli_run._approval_wait_enabled(no_wait=True, fast=False) is False
    assert cli_run._approval_wait_enabled(no_wait=False, fast=True) is False

    monkeypatch.setenv("REVMEM_CLI_FAST", "1")
    assert cli_run._approval_wait_enabled(no_wait=False, fast=False) is False


def test_main_fast_scaffold_disables_wait_and_pacing(monkeypatch):
    captured = {}

    def fake_run_scaffold(
        name,
        wait=True,
        delay_scale=None,
        approval_timeout=None,
        approval_interval=None,
    ):
        captured.update(
            name=name,
            wait=wait,
            delay_scale=delay_scale,
            approval_timeout=approval_timeout,
            approval_interval=approval_interval,
        )

    monkeypatch.setattr(cli_run, "run_scaffold", fake_run_scaffold)
    monkeypatch.setattr(sys, "argv", ["cli.run", "--fast"])

    cli_run.main()

    assert captured == {
        "name": "s3",
        "wait": False,
        "delay_scale": 0.0,
        "approval_timeout": None,
        "approval_interval": None,
    }


def test_main_fast_scaffold_all_runs_every_scaffold_session(monkeypatch):
    calls = []

    def fake_run_scaffold(
        name,
        wait=True,
        delay_scale=None,
        approval_timeout=None,
        approval_interval=None,
    ):
        calls.append((name, wait, delay_scale))

    monkeypatch.setattr(cli_run, "run_scaffold", fake_run_scaffold)
    monkeypatch.setattr(sys, "argv", ["cli.run", "--fast", "--all"])

    cli_run.main()

    assert calls == [("s1", False, 0.0), ("s3", False, 0.0)]


def test_scaffold_session_3_uses_controller_route():
    scenario = cli_run.SCAFFOLD_SCENARIOS["s3"]

    assert scenario["approver_role"] == "controller"
    assert scenario["approver_email"] == "controller@example.com"


def test_live_all_uses_fresh_agent_by_default(monkeypatch):
    captured = {}

    def fake_run_live_all(
        wait=True,
        approval_timeout=None,
        approval_interval=None,
        pause_between=True,
        agent_name=None,
        debug=False,
    ):
        captured.update(
            wait=wait,
            pause_between=pause_between,
            agent_name=agent_name,
            debug=debug,
        )

    monkeypatch.setattr(cli_run, "run_live_all", fake_run_live_all)
    monkeypatch.setattr(cli_run, "_fresh_agent_name", lambda: "fresh-agent")
    monkeypatch.setattr(sys, "argv", ["cli.run", "--live", "--fast", "--all"])

    cli_run.main()

    assert captured == {
        "wait": False,
        "pause_between": False,
        "agent_name": "fresh-agent",
        "debug": False,
    }


def test_live_repeat_seeds_once_then_repeats_generalization(monkeypatch):
    sessions = []

    def fake_run_live(
        session_number,
        wait=True,
        env_id=None,
        prev_interaction=None,
        approval_timeout=None,
        approval_interval=None,
        agent_name=None,
        debug=False,
    ):
        sessions.append(session_number)
        return {
            "session_number": session_number,
            "environment_id": f"env-{len(sessions)}",
            "interaction_id": f"interaction-{len(sessions)}",
            "deal": "acme" if session_number in (1, 2) else "globex",
            "tier": "observer",
            "reputation": 0.1,
            "memories_used": 0,
            "outcome": {},
        }

    monkeypatch.setattr(cli_run, "run_live", fake_run_live)

    results = cli_run.run_live_repeat(3, wait=False, agent_name="fresh-agent")

    assert sessions == [1, 2, 3, 3, 3]
    assert [r["run"] for r in results] == ["Seed 1/2", "Seed 2/2", 1, 2, 3]


def test_approval_polling_options_are_bounded(monkeypatch):
    monkeypatch.setenv("REVMEM_APPROVAL_TIMEOUT", "0.25")
    monkeypatch.setenv("REVMEM_APPROVAL_INTERVAL", "0")

    assert cli_run._resolve_approval_timeout() == 0.25
    assert cli_run._resolve_approval_interval() == 0.01
