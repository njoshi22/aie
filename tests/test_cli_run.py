from __future__ import annotations

import sys

from agent import revmem_client
from cli import run as cli_run
from cli.run import approval_source_label, live_runtime_error


def test_live_runtime_rejects_implicit_stub_mode() -> None:
    error = live_runtime_error(
        stub_mode=True,
        base_url="",
        allow_stub_live=False,
    )

    assert error is not None
    assert "requires REVMEM_BASE_URL" in error
    assert "--allow-stub-live" in error


def test_live_runtime_allows_real_revmem_api() -> None:
    assert live_runtime_error(
        stub_mode=False,
        base_url="http://127.0.0.1:8000",
        allow_stub_live=False,
    ) is None


def test_live_runtime_allows_explicit_stub_override() -> None:
    assert live_runtime_error(
        stub_mode=True,
        base_url="",
        allow_stub_live=True,
    ) is None


def test_approval_source_label_for_hook() -> None:
    assert approval_source_label("pre_tool_hook") == "pre-tool-use hook"


def test_approval_source_label_for_model() -> None:
    assert approval_source_label("model") == "model tool call"


def test_main_live_all_uses_fresh_agent_by_default(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run_live_all(
        wait: bool = True,
        approval_timeout: float | None = None,
        approval_interval: float | None = None,
        pause_between: bool = True,
        agent_name: str | None = None,
        debug: bool = False,
    ) -> list[dict[str, object]]:
        captured.update(
            wait=wait,
            pause_between=pause_between,
            agent_name=agent_name,
            debug=debug,
        )
        return []

    monkeypatch.setattr(revmem_client, "STUB_MODE", False)
    monkeypatch.setattr(revmem_client, "REVMEM_BASE_URL", "http://127.0.0.1:8000")
    monkeypatch.setattr(cli_run, "run_live_all", fake_run_live_all)
    monkeypatch.setattr(cli_run, "_fresh_agent_name", lambda: "fresh-agent", raising=False)
    monkeypatch.setattr(sys, "argv", ["cli.run", "--live", "--fast", "--all"])

    cli_run.main()

    assert captured == {
        "wait": False,
        "pause_between": False,
        "agent_name": "fresh-agent",
        "debug": False,
    }


def test_run_live_all_resets_context_when_deal_changes(monkeypatch) -> None:
    calls: list[tuple[int, str | None, str | None]] = []

    def fake_run_live(
        session_number: int,
        wait: bool = True,
        env_id: str | None = None,
        prev_interaction: str | None = None,
        approval_timeout: float | None = None,
        approval_interval: float | None = None,
        agent_name: str | None = None,
        debug: bool = False,
    ) -> dict[str, object]:
        calls.append((session_number, env_id, prev_interaction))
        return {
            "session_number": session_number,
            "environment_id": f"env-{session_number}",
            "interaction_id": f"interaction-{session_number}",
            "deal": "acme" if session_number in (1, 2) else "globex",
            "tier": "observer",
            "reputation": 0.1,
            "memories_used": 0,
            "outcome": {},
        }

    monkeypatch.setattr(cli_run, "run_live", fake_run_live)

    cli_run.run_live_all(wait=False, pause_between=False, agent_name="fresh-agent")

    assert calls == [
        (1, None, None),
        (2, "env-1", "interaction-1"),
        (3, None, None),
    ]
