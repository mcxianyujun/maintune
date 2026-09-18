import asyncio
import json
import zipfile
from pathlib import Path

import pytest

from maintainer.db import Config, Repository, Task, Timeline, database
from maintainer.plugin_system import (
    PluginCapabilityBroker,
    PluginCapabilityError,
    PluginPackageError,
    PluginPackageManager,
    PluginProcess,
    _safe_member,
    load_manifest,
    make_event,
    parse_manifest_yaml,
)
from maintainer.plugin_manager import PluginManager
from maintainer.security import Vault
from cryptography.fernet import Fernet


MANIFEST = """id: official.test-plugin
name: Test Plugin
version: 0.1.0-dev
api_version: 1
publisher: mcxianyujun
description: External test plugin
maintune:
  min_version: 0.1.0
capabilities:
  - event.subscribe
  - task.read
  - owner_decision.submit
entrypoint:
  python: test_plugin.main
config:
  bridge_token:
    type: secret
    title: Bridge token
    required: true
  mode:
    type: select
    title: Mode
    default: safe
    options:
      - safe
      - quiet
"""


PLUGIN_MAIN = r'''import asyncio
import json
import sys

pending = {}

async def write(value):
    sys.stdout.write(json.dumps(value, separators=(",", ":")) + "\n")
    sys.stdout.flush()

async def capability(name, action, **values):
    request_id = "plugin-" + str(len(pending) + 1)
    future = asyncio.get_running_loop().create_future()
    pending[request_id] = future
    await write({"jsonrpc":"2.0","id":request_id,"method":"capability.call","params":{"capability":name,"action":action,**values}})
    return await future

async def handle(message):
    method = message.get("method")
    request_id = message.get("id")
    if method == "lifecycle.start": result = {"started": True}
    elif method == "lifecycle.stop": result = {"stopped": True}
    elif method == "health": result = {"ok": True}
    elif method == "transport.message":
        params = message.get("params", {})
        if params.get("type") == "status":
            result = {"type":"response","data":await capability("task.read", "status")}
        else: result = {"type":"ack"}
    else: result = {}
    if request_id: await write({"jsonrpc":"2.0","id":request_id,"result":result})

async def main():
    loop = asyncio.get_running_loop()
    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if not line: return
        message = json.loads(line)
        if "method" in message: asyncio.create_task(handle(message))
        elif "id" in message:
            future = pending.pop(str(message["id"]), None)
            if future:
                if "error" in message: future.set_exception(RuntimeError(message["error"]["message"]))
                else: future.set_result(message.get("result"))

asyncio.run(main())
'''


def package(path: Path, manifest: str = MANIFEST, extra=None):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("manifest.yaml", manifest)
        archive.writestr("src/test_plugin/__init__.py", "")
        archive.writestr("src/test_plugin/main.py", PLUGIN_MAIN)
        archive.writestr("README.md", "test")
        archive.writestr("requirements.lock", "")
        for name, value in extra or []:
            archive.writestr(name, value)


def test_manifest_parser_and_schema(tmp_path):
    path = tmp_path / "manifest.yaml"
    path.write_text(MANIFEST, encoding="utf-8")
    manifest = load_manifest(path)
    assert manifest.id == "official.test-plugin"
    assert manifest.config["bridge_token"].type == "secret"
    assert parse_manifest_yaml(MANIFEST)["maintune"]["min_version"] == "0.1.0"


@pytest.mark.parametrize("unsafe", ["../escape.py", "/absolute.py"])
def test_package_rejects_path_traversal_and_unsafe_paths(tmp_path, unsafe):
    archive = tmp_path / "bad.mtp"
    package(archive, extra=[(unsafe, "bad")])
    manager = PluginPackageManager(tmp_path / "plugins", "0.1.0-preview.1")
    with pytest.raises(PluginPackageError, match="unsafe path"):
        manager.validate(archive)


def test_package_rejects_backslash_path():
    info = zipfile.ZipInfo("placeholder")
    info.filename = "src\\escape.py"
    with pytest.raises(PluginPackageError, match="unsafe path"):
        _safe_member(info)


def test_package_rejects_symlink(tmp_path):
    archive = tmp_path / "bad.mtp"
    package(archive)
    with zipfile.ZipFile(archive, "a") as bundle:
        info = zipfile.ZipInfo("src/link")
        info.create_system = 3
        info.external_attr = 0o120777 << 16
        bundle.writestr(info, "target")
    manager = PluginPackageManager(tmp_path / "plugins", "0.1.0-preview.1")
    with pytest.raises(PluginPackageError, match="symlinks"):
        manager.validate(archive)


@pytest.mark.parametrize(
    "manifest,error",
    [
        (MANIFEST.replace("api_version: 1", "api_version: 2"), "Unsupported Plugin API"),
        (MANIFEST.replace("min_version: 0.1.0", "min_version: 99.0.0"), "newer Maintune"),
        (MANIFEST + "unknown_field: true\n", "schema validation"),
    ],
)
def test_package_rejects_incompatible_or_invalid_manifest(tmp_path, manifest, error):
    archive = tmp_path / "bad.mtp"
    package(archive, manifest)
    manager = PluginPackageManager(tmp_path / "plugins", "0.1.0-preview.1")
    with pytest.raises(PluginPackageError, match=error):
        manager.validate(archive)


def test_package_rejects_excessive_file_count(tmp_path, monkeypatch):
    archive = tmp_path / "large.mtp"
    package(archive, extra=[("extra.txt", "small")])
    monkeypatch.setattr("maintainer.plugin_system.MAX_ARCHIVE_FILES", 4)
    manager = PluginPackageManager(tmp_path / "plugins", "0.1.0-preview.1")
    with pytest.raises(PluginPackageError, match="too many files"):
        manager.validate(archive)


def test_install_discover_duplicate_and_uninstall(tmp_path):
    archive = tmp_path / "plugin.mtp"
    package(archive)
    manager = PluginPackageManager(tmp_path / "plugins", "0.1.0-preview.1")
    manifest = manager.install(archive)
    assert manifest.id == "official.test-plugin"
    assert [item.id for item in manager.discover()] == ["official.test-plugin"]
    with pytest.raises(PluginPackageError, match="already installed"):
        manager.install(archive)
    manager.uninstall(manifest.id)
    assert manager.discover() == []


def test_process_isolated_rpc_and_capability_enforcement(tmp_path):
    archive = tmp_path / "plugin.mtp"
    package(archive)
    packages = PluginPackageManager(tmp_path / "plugins", "0.1.0-preview.1")
    manifest = packages.install(archive)
    calls = []

    async def capability(name, params):
        calls.append((name, params["action"]))
        if name != "task.read":
            raise PluginCapabilityError("denied")
        return {"status": "ok"}

    async def scenario():
        process = PluginProcess(manifest, packages.installed / manifest.id, packages.runtime / manifest.id, capability)
        await process.start()
        try:
            result = await process.request("transport.message", {"type": "status"})
            assert result == {"type": "response", "data": {"status": "ok"}}
            assert calls == [("task.read", "status")]
            assert process.state() == "running"
        finally:
            await process.stop()
    asyncio.run(scenario())


def test_plugin_crash_does_not_crash_host(tmp_path):
    archive = tmp_path / "crash.mtp"
    crash_manifest = MANIFEST.replace("official.test-plugin", "official.crash-plugin")
    package(archive, crash_manifest)
    packages = PluginPackageManager(tmp_path / "plugins", "0.1.0-preview.1")
    manifest = packages.install(archive)

    async def capability(name, params):
        return {}

    async def scenario():
        process = PluginProcess(manifest, packages.installed / manifest.id, packages.runtime / manifest.id, capability)
        await process.start()
        process.process.kill()
        await process.process.wait()
        await asyncio.sleep(0)
        with pytest.raises(Exception, match="not running|exited"):
            await process.request("health", {})
    asyncio.run(scenario())
    assert 2 + 2 == 4


@pytest.fixture
def broker(tmp_path):
    engine, sessions = database(f"sqlite:///{tmp_path / 'plugin.db'}")
    yield sessions
    engine.dispose()


def test_capabilities_task_read_owner_decision_and_replay(broker):
    with broker.begin() as db:
        db.add(Repository(full_name="owner/repo", installation_id=123, data={"enabled": True, "default_branch": "main", "private_token": "never"}))
        task = Task(kind="issue", repository="owner/repo", number=7, event="issues.opened", delivery_id="plugin-owner", status="waiting_for_owner", data={"summary": "Choose"})
        db.add(task)
        db.flush()
        task_id = task.id
    async def scenario():
        denied = PluginCapabilityBroker(broker, "official.denied", {"task.read"})
        with pytest.raises(PluginCapabilityError, match="not granted"):
            await denied.call("owner_decision.submit", {"action": "submit"})
        broker_api = PluginCapabilityBroker(broker, "official.test-plugin", {"repository.read", "task.read", "owner_decision.submit"})
        repositories = await broker_api.call("repository.read", {"action": "list"})
        assert repositories == [{"full_name": "owner/repo", "enabled": True, "default_branch": "main"}]
        assert "private_token" not in repositories[0] and "installation_id" not in repositories[0]
        detail = await broker_api.call("task.read", {"action": "get", "task_id": task_id})
        assert detail["status"] == "waiting_for_owner"
        assert detail["ref"] == task_id[:8]
        result = await broker_api.call("owner_decision.submit", {"action": "submit", "task_id": detail["ref"], "decision": "implement", "replay_key": "request-0001"})
        assert result == {"status": "queued", "action": "implement"}
        with pytest.raises(PluginCapabilityError, match="replay"):
            await broker_api.call("owner_decision.submit", {"action": "submit", "task_id": task_id, "decision": "implement", "replay_key": "request-0001"})
    asyncio.run(scenario())
    with broker() as db:
        task = db.get(Task, task_id)
        assert task.status == "queued" and task.data["owner_decision_source"] == "official.test-plugin"
        event = db.scalar(__import__("sqlalchemy").select(Timeline).where(Timeline.task_id == task_id, Timeline.kind == "owner_decision"))
        assert event.data == {"action": "implement", "source": "official.test-plugin"}


def test_short_task_references_are_unique_and_ambiguous_prefixes_are_rejected(broker):
    first_id = "deadbeef-0000-4000-8000-000000000001"
    second_id = "deadbeef-0000-4000-8000-000000000002"
    with broker.begin() as db:
        db.add_all([
            Task(id=first_id, kind="issue", repository="owner/repo", number=1, event="issues.opened", delivery_id="short-1", status="waiting_for_owner", data={}),
            Task(id=second_id, kind="issue", repository="owner/repo", number=2, event="issues.opened", delivery_id="short-2", status="waiting_for_owner", data={}),
        ])
    async def scenario():
        api = PluginCapabilityBroker(broker, "official.test-plugin", {"task.read", "owner_decision.submit"})
        tasks = await api.call("task.read", {"action": "list"})
        references = {item["id"]: item["ref"] for item in tasks}
        assert references[first_id] != references[second_id]
        assert len(references[first_id]) > 8 and len(references[second_id]) > 8
        with pytest.raises(PluginCapabilityError, match="ambiguous"):
            await api.call("task.read", {"action": "get", "task_id": "deadbeef"})
        detail = await api.call("task.read", {"action": "get", "task_id": references[first_id]})
        assert detail["id"] == first_id
    asyncio.run(scenario())


def test_event_model_redacts_sensitive_fields(broker):
    with broker.begin() as db:
        task = Task(kind="issue", repository="owner/repo", number=8, event="issues.opened", delivery_id="event", status="running", data={"summary": "Visible"})
        db.add(task)
        db.flush()
        event = make_event("task.started", task, {"reason": "ok", "api_token": "never"})
    assert event.protocol == "maintune.plugin.v1"
    assert event.repository == "owner/repo"
    assert event.data == {"reason": "ok"}
    assert event.event_id.startswith("evt_")
    assert event.task["ref"] == task.id[:8]


def test_manager_secret_masking_token_rotation_and_event_ack(tmp_path):
    archive = tmp_path / "plugin.mtp"
    package(archive)
    engine, sessions = database(f"sqlite:///{tmp_path / 'manager.db'}")
    manager = PluginManager(tmp_path / "plugins", "0.1.0-preview.1", sessions, Vault(Fernet.generate_key().decode()))
    inbox = manager.packages.inbox / archive.name
    inbox.write_bytes(archive.read_bytes())
    manager.install(archive.name)
    assert manager.readme("official.test-plugin") == "test"
    assert manager.view("official.test-plugin")["has_readme"] is True
    manager.configure("official.test-plugin", {"bridge_token": "first-token-" + "x" * 40})
    assert manager.view("official.test-plugin")["config"]["bridge_token"] == "********"
    old_token = manager._secret("official.test-plugin", "bridge_token")
    new_token = manager.regenerate_secret("official.test-plugin", "bridge_token")
    assert old_token != new_token and manager._secret("official.test-plugin", "bridge_token") == new_token

    class Socket:
        def __init__(self): self.messages = []
        async def send_json(self, value): self.messages.append(value)

    async def scenario():
        await manager.enable("official.test-plugin")
        assert not await manager.authenticate_transport("official.test-plugin", {"protocol": "maintune.astrbot.v1", "type": "authenticate", "token": old_token})
        assert await manager.authenticate_transport("official.test-plugin", {"protocol": "maintune.astrbot.v1", "type": "authenticate", "token": new_token})
        event = make_event("task.failed", data={"reason": "test"})
        await manager.publish(event)
        assert event.event_id in manager._load_outbox("official.test-plugin")
        await manager.transport_message("official.test-plugin", {"type": "ack", "event_id": event.event_id})
        assert event.event_id not in manager._load_outbox("official.test-plugin")
        await manager.stop()
    asyncio.run(scenario())
    engine.dispose()


def test_manager_reload_and_disable_close_transports_and_preserve_config(tmp_path):
    archive = tmp_path / "plugin.mtp"
    package(archive)
    engine, sessions = database(f"sqlite:///{tmp_path / 'lifecycle.db'}")
    manager = PluginManager(tmp_path / "plugins", "0.1.0-preview.1", sessions, Vault(Fernet.generate_key().decode()))
    inbox = manager.packages.inbox / archive.name
    inbox.write_bytes(archive.read_bytes())
    manager.install(archive.name)
    manager.configure("official.test-plugin", {"bridge_token": "token-" + "x" * 40, "mode": "quiet"})

    class Socket:
        def __init__(self): self.closed = []
        async def close(self, code): self.closed.append(code)

    async def scenario():
        await manager.enable("official.test-plugin")
        first_process = manager.processes["official.test-plugin"]
        first_socket = Socket()
        manager.connections["official.test-plugin"] = {first_socket}
        manager.connection_state["official.test-plugin"] = {"instance": "test"}
        reloaded = await manager.reload("official.test-plugin")
        assert first_socket.closed == [1012]
        assert reloaded["enabled"] is True and reloaded["runtime_status"] == "running"
        assert manager.processes["official.test-plugin"] is not first_process
        assert reloaded["config"]["mode"] == "quiet"
        assert reloaded["config"]["bridge_token"] == "********"

        second_socket = Socket()
        manager.connections["official.test-plugin"] = {second_socket}
        disabled = await manager.disable("official.test-plugin")
        assert second_socket.closed == [1012]
        assert disabled["enabled"] is False and disabled["runtime_status"] == "stopped"
        assert disabled["config"]["mode"] == "quiet"
        assert "official.test-plugin" not in manager.connections
        await manager.stop()
    asyncio.run(scenario())
    engine.dispose()


def test_manager_rejects_oversized_readme(tmp_path):
    archive = tmp_path / "plugin.mtp"
    package(archive)
    engine, sessions = database(f"sqlite:///{tmp_path / 'readme.db'}")
    manager = PluginManager(tmp_path / "plugins", "0.1.0-preview.1", sessions, Vault(Fernet.generate_key().decode()))
    inbox = manager.packages.inbox / archive.name
    inbox.write_bytes(archive.read_bytes())
    manager.install(archive.name)
    (manager.packages.installed / "official.test-plugin" / "README.md").write_text("x" * (512 * 1024 + 1), encoding="utf-8")
    with pytest.raises(PluginPackageError, match="too large"):
        manager.readme("official.test-plugin")
    engine.dispose()
