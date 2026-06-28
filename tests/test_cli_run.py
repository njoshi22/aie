from __future__ import annotations

from cli.run import live_runtime_error


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
