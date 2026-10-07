"""A cold Docker port must not be mistaken for a failed running application."""
import importlib.util
from pathlib import Path

import pytest


def load(monkeypatch):
    monkeypatch.setenv("MAINTUNE_CI_ADMIN_TOKEN", "ci-test-only")
    path = Path(__file__).resolve().parents[1] / "scripts/container_smoke.py"
    spec = importlib.util.spec_from_file_location("container_smoke", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    return module


def test_readiness_retries_connection_reset_before_health(monkeypatch):
    smoke = load(monkeypatch)
    calls = []
    expected = {"status": "ok", "version": "0.1.0", "schema": 4}

    def request(*args, **kwargs):
        calls.append(args)
        if len(calls) == 1:
            raise ConnectionResetError("cold Docker port")
        return expected

    monkeypatch.setattr(smoke, "call", request)
    assert smoke.wait_for_health(attempts=2) == expected
    assert len(calls) == 2


def test_readiness_deadline_and_invalid_response_fail_closed(monkeypatch):
    smoke = load(monkeypatch)

    def unavailable(*args, **kwargs):
        raise ConnectionResetError("not ready")

    monkeypatch.setattr(smoke, "call", unavailable)
    with pytest.raises(SystemExit, match="health timeout"):
        smoke.wait_for_health(attempts=2)
    monkeypatch.setattr(smoke, "call", lambda *args, **kwargs: {"status": "ok", "version": "wrong", "schema": 4})
    with pytest.raises(AssertionError):
        smoke.main()
