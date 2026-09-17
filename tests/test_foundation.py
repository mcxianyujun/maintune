import asyncio
import re
from dataclasses import replace

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import select

from maintainer.api import create_app
from maintainer.db import Config, Provider, Run
from maintainer.policy import MergeEvidence, merge_blockers
from maintainer.providers import Completion
from maintainer.sandboxes import LocalSandbox
from maintainer.security import Settings


@pytest.fixture
def app(tmp_path):
    return create_app(Settings(admin_token="a" * 40, encryption_key=Fernet.generate_key().decode(), database_url=f"sqlite:///{tmp_path / 'app.db'}", workspace_root=str(tmp_path / "workspaces")))


@pytest.fixture
def client(app):
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer " + "a" * 40
        yield client


def provider(client):
    response = client.post("/api/providers", json={"name": "Test", "base_url": "https://models.example/v1", "api_key": "secret-test-value", "models": ["a", "b"]})
    assert response.status_code == 201
    return response.json()


def test_public_frontend_assets_are_not_captured_by_api_auth(client):
    page = client.get("/")
    assert page.status_code == 200
    assert "no-store" in page.headers["cache-control"]
    scripts = re.findall(r'src="([^"]+\.js)"', page.text)
    styles = re.findall(r'href="([^"]+\.css)"', page.text)
    assert len(scripts) == len(styles) == 1
    javascript = client.get(scripts[0], headers={"Authorization": ""})
    stylesheet = client.get(styles[0], headers={"Authorization": ""})
    assert javascript.status_code == 200 and "javascript" in javascript.headers["content-type"]
    assert stylesheet.status_code == 200 and "text/css" in stylesheet.headers["content-type"]
    assert "immutable" in javascript.headers["cache-control"]
    assert "Unauthorized" not in javascript.text


def test_health_reports_release_and_schema(client):
    result = client.get("/healthz").json()
    assert result == {"status": "ok", "version": "0.1.0-preview.1", "schema": 4}


def test_setup_status_is_computed_and_diagnostics_complete(client, app, monkeypatch):
    initial = client.get("/api/setup/status").json()
    assert initial["steps"]["system"] is True
    assert initial["complete"] is False

    p = provider(client)
    configure(client, p["id"])
    assert client.put("/api/github", json={
        "app_id": 123,
        "installation_id": 456,
        "private_key": "private-key-test-value",
        "webhook_secret": "webhook-secret-test-value",
        "api_url": "https://api.github.com",
    }).status_code == 200
    repository = {
        "full_name": "owner/repository", "installation_id": 456, "enabled": True,
        "auto_handle_issues": True, "auto_review_prs": True, "auto_merge": False,
        "default_branch": "main", "install_command": "", "test_command": "pytest",
        "lint_command": "", "build_command": "", "working_directory": ".",
        "additional_instructions": "",
    }
    assert client.put("/api/repositories/owner/repository", json=repository).status_code == 200

    class DiagnosticProvider:
        def __init__(self, *args): pass
        async def models(self): return ["a", "b"]

    class FakeGitHub:
        def __init__(self, *args): pass
        async def installations(self): return [{"id": 456, "account": {"login": "owner"}}]

    app.state.provider_factory = DiagnosticProvider
    monkeypatch.setattr("maintainer.api.GitHubAppClient", FakeGitHub)
    response = client.post("/api/setup/diagnostics")
    assert response.status_code == 200
    result = response.json()
    assert result["complete"] is True
    assert all(check["ok"] for check in result["checks"].values())
    assert "private-key-test-value" not in response.text
    assert "webhook-secret-test-value" not in response.text


def test_setup_status_accepts_saved_local_sandbox_secret(client, app):
    """Encrypted storage metadata must not be parsed as public Sandbox input."""
    with app.state.sessions.begin() as db:
        row = db.get(Config, "sandbox")
        row.data = {**row.data, "encrypted_key": None}
    response = client.get("/api/setup/status")
    assert response.status_code == 200
    assert response.json()["steps"]["sandbox"] is True


def configure(client, pid):
    settings = client.get("/api/settings").json()
    settings["model"] = {"provider": pid, "model": "a"}
    assert client.put("/api/settings", json=settings).status_code == 200


def test_auth_and_no_secret_echo(client, app):
    assert client.get("/api/settings", headers={"Authorization": ""}).status_code == 401
    p = provider(client)
    assert "secret-test-value" not in str(p)
    assert "secret-test-value" not in client.get("/api/providers").text
    with app.state.sessions() as db:
        row = db.get(Provider, p["id"])
        assert "secret-test-value" not in row.encrypted_key
        assert app.state.vault.decrypt(row.encrypted_key) == "secret-test-value"
    update = {k: p[k] for k in ("name", "type", "base_url", "models")}
    client.put(f"/api/providers/{p['id']}", json=update)
    with app.state.sessions() as db:
        assert app.state.vault.decrypt(db.get(Provider, p["id"]).encrypted_key) == "secret-test-value"
    update["api_key"] = "replacement"
    assert "replacement" not in client.put(f"/api/providers/{p['id']}", json=update).text


def test_reference_integrity(client):
    p = provider(client)
    configure(client, p["id"])
    assert client.delete(f"/api/providers/{p['id']}").status_code == 409
    assert client.put(f"/api/providers/{p['id']}", json={"name": "Test", "base_url": "https://models.example/v1", "models": ["b"]}).status_code == 409
    settings = client.get("/api/settings").json()
    settings["model"]["model"] = "missing"
    assert client.put("/api/settings", json=settings).status_code == 422


def test_run_inheritance_audit_tokens_and_failure(client, app):
    calls = []

    class FakeProvider:
        def __init__(self, url, key):
            pass

        async def complete(self, model, system, prompt, timeout):
            calls.append((model, system))
            return Completion(text="secret-test-value resolved", input_tokens=12, output_tokens=8, total_tokens=20, usage_reported=True)

    app.state.provider_factory = FakeProvider
    p = provider(client)
    configure(client, p["id"])
    response = client.post("/api/runs", json={"agent": "issue_analyzer", "prompt": "Inspect"})
    assert response.status_code == 201
    assert response.json()["status"] == "completed"
    assert "secret-test-value" not in response.text
    assert calls[0][0] == "a" and "reproduction" in calls[0][1]
    assert client.get("/api/dashboard").json()["tokens"]["24h"]["total"] == 20
    assert len(client.get("/api/runs").json()) == 1

    class Failure(FakeProvider):
        async def complete(self, *args):
            raise RuntimeError("secret-test-value")

    app.state.provider_factory = Failure
    response = client.post("/api/runs", json={"prompt": "Inspect"})
    assert response.json()["status"] == "failed"
    assert "secret-test-value" not in response.text
    assert client.get("/api/dashboard").json()["counts"]["failed"] == 1


def test_agent_disabled_and_deleted_not_reseeded(client, app):
    agent = client.get("/api/agents").json()[0]
    agent["enabled"] = False
    client.put(f"/api/agents/{agent['identifier']}", json=agent)
    assert client.post("/api/runs", json={"agent": agent["identifier"], "prompt": "x"}).status_code == 409
    assert client.delete(f"/api/agents/{agent['identifier']}").status_code == 204
    restarted = create_app(app.state.settings)
    with TestClient(restarted) as c:
        assert len(c.get("/api/agents", headers=client.headers).json()) == 4


def test_restart_marks_interrupted(app):
    with app.state.sessions.begin() as db:
        db.add(Run(status="running", data={}))
    with TestClient(app):
        with app.state.sessions() as db:
            assert db.scalar(select(Run)).status == "interrupted"


def test_local_probe_cleanup(client, app):
    assert client.post("/api/sandbox/test").json()["ok"]
    from pathlib import Path
    assert list(Path(app.state.settings.workspace_root).iterdir()) == []


@pytest.mark.parametrize("name", ["../secret", "/etc/passwd", "C:\\secret", "a/../../secret", "a:stream", "\\\\server\\share", "a\x00b"])
def test_path_escape(tmp_path, name):
    sandbox = LocalSandbox(str(tmp_path))
    asyncio.run(sandbox.create("test"))
    with pytest.raises(ValueError):
        asyncio.run(sandbox.write_file("test", name, "x"))


def test_local_shell_timeout_and_secret_isolation(tmp_path, monkeypatch):
    import sys

    sandbox = LocalSandbox(str(tmp_path))
    asyncio.run(sandbox.create("test"))
    monkeypatch.setenv("MAINTAINER_ADMIN_TOKEN", "must-not-leak")
    command = f'"{sys.executable}" -c "import os; print(os.environ.get(\'MAINTAINER_ADMIN_TOKEN\', \'absent\'))"'
    result = asyncio.run(sandbox.exec("test", command, 5))
    assert result["exit_code"] == 0 and "absent" in result["output"] and "must-not-leak" not in result["output"]
    with pytest.raises(TimeoutError):
        asyncio.run(sandbox.exec("test", f'"{sys.executable}" -c "import time; time.sleep(3)"', 1))


def test_policy_fails_closed():
    assert merge_blockers(MergeEvidence())
    safe = MergeEvidence(True, True, True, False, True, False, False, False, False, "abc", "abc")
    assert merge_blockers(safe) == []
    assert merge_blockers(replace(safe, current_sha="def"))
    assert merge_blockers(replace(safe, sensitive_files=True))
