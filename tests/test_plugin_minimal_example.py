"""Real .mtp installation and isolated SDK process, not mocked transport."""
import asyncio
import importlib.util
import json
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from maintainer.db import Config, database
from maintainer.plugin_manager import PluginManager
from maintainer.security import Vault
from test_foundation import app, client

EXAMPLE = Path(__file__).resolve().parents[1] / "examples/plugins/example"
PLUGIN_ID = "example.workflow-notes"
TOOL = PLUGIN_ID + "/add"
SECRET = "TEST_ONLY_MINIMAL_SECRET"


def build(path):
    spec = importlib.util.spec_from_file_location("minimal_builder", EXAMPLE / "build_mtp.py")
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    builder.build(path)


def test_real_minimal_package_process_hook_tool_and_persistence(tmp_path, caplog):
    engine, sessions = database(f"sqlite:///{tmp_path / 'isolated.db'}")
    manager = PluginManager(tmp_path / "plugins", "0.1.0-preview.3", sessions,
                            Vault(Fernet.generate_key().decode()))
    archive = manager.packages.inbox / "example.mtp"
    build(archive)
    installed = manager.install(archive.name)
    assert installed["api_version"] == 2
    view = manager.configure(PLUGIN_ID, {"label": "Checkpoint", "demo_secret": SECRET})
    assert SECRET not in json.dumps(view)
    assert view["config"]["demo_secret"] == "********"
    with sessions() as db:
        rows = db.query(Config).all()
        assert SECRET not in json.dumps([row.data for row in rows])
    with pytest.raises(Exception):
        manager.configure(PLUGIN_ID, {"label": 17})

    async def scenario():
        try:
            enabled = await manager.enable(PLUGIN_ID)
            assert enabled["enabled"] and enabled["runtime_status"] == "running"
            assert {(r["kind"], r["identifier"]) for r in enabled["registrations"]} == {
                ("hook", PLUGIN_ID + "/task.started"), ("tool", TOOL)}
            assert manager.agent_tools("code_worker") == []
            manager.set_agent_tools("code_worker", [TOOL])
            assert [t.identifier for t in manager.agent_tools("code_worker")] == [TOOL]
            assert manager.agent_tools("issue_analyzer") == []
            result = await manager.invoke_tool(TOOL, {"a": 2, "b": 3})
            assert result == {"label": "Checkpoint", "total": 5}
            with pytest.raises(Exception):
                await manager.invoke_tool(TOOL, {"a": 2, "b": 3, "kind": "internal"})
            with pytest.raises(Exception):
                await manager.invoke_tool(TOOL, {"a": "2", "b": 3})
            await manager.dispatch_hook("task.started", {"task_id": "public-task", "extra": "not persisted"})
            data = manager.packages.root / "data" / PLUGIN_ID / "last-task.json"
            assert json.loads(data.read_text()) == {"task_id": "public-task"}
            disabled = await manager.disable(PLUGIN_ID)
            assert not disabled["enabled"] and disabled["runtime_status"] == "stopped"
            assert manager.registry.list() == []
            with pytest.raises(Exception):
                await manager.invoke_tool(TOOL, {"a": 2, "b": 3})
            assert data.is_file()
            assert manager.view(PLUGIN_ID)["config"]["demo_secret"] == "********"
            await manager.enable(PLUGIN_ID)
            assert await manager.invoke_tool(TOOL, {"a": 0, "b": -1}) == {"label": "Checkpoint", "total": -1}
            assert json.loads(data.read_text()) == {"task_id": "public-task"}
            assert SECRET not in data.read_text() + json.dumps(result) + caplog.text
        finally:
            await manager.stop()

    try:
        asyncio.run(scenario())
    finally:
        engine.dispose()


def test_real_example_config_http_api_never_returns_secret(app, client):
    build(app.state.plugins.packages.inbox / "minimal.mtp")
    assert client.post("/api/plugins/install/minimal.mtp").status_code == 201
    response = client.put(f"/api/plugins/{PLUGIN_ID}/config", json={"label": "HTTP", "demo_secret": SECRET})
    assert response.status_code == 200
    assert SECRET not in response.text
    assert response.json()["config"]["demo_secret"] == "********"
    response = client.get("/api/plugins")
    assert response.status_code == 200 and SECRET not in response.text
