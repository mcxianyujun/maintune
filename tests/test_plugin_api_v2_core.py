import asyncio
import json
import stat
import zipfile
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from pydantic import BaseModel

from maintainer.db import database
from maintainer.db import Config, Outbox, Repository, Task, Timeline
from maintainer.plugin_manager import PluginManager
from maintainer.plugin_api_v2 import PluginRegistry
from maintainer.plugin_system import PluginPackageError
from maintainer.security import Vault
from maintainer.runtime import public_plugin_tool_arguments
from maintainer.tasks import TaskProcessor


MANIFEST = {
    "id": "example.v2-test",
    "name": "V2 test",
    "version": "0.1.0-dev",
    "plugin_api": 2,
    "publisher": "mcxianyujun",
    "license": "MIT",
    "maintune": {"min_version": "0.1.0"},
    "runtime": {"default": "isolated", "supported": ["isolated"]},
    "entrypoint": {"python": "example.main"},
    "config_schema": {
        "type": "object",
        "properties": {
            "prefix": {"type": "string", "default": "result"},
            "api_key": {"type": "string", "secret": True},
        },
        "additionalProperties": False,
    },
}

SOURCE = '''
def search(context, query: str) -> str:
    return context.config["prefix"] + ": " + query

def register(api):
    api.register_tool("search", search, description="Return a test result", recommended_agents=["code_worker"])
'''


def package(path, manifest=MANIFEST, source=SOURCE):
    with zipfile.ZipFile(path, "w") as bundle:
        bundle.writestr("manifest.yaml", json.dumps(manifest))
        bundle.writestr("src/example/__init__.py", "")
        bundle.writestr("src/example/main.py", source)
        bundle.writestr("README.md", "# V2 test")


def test_v2_manifest_and_isolated_tool_runtime(tmp_path):
    engine, sessions = database(f"sqlite:///{tmp_path / 'plugin-v2.db'}")
    manager = PluginManager(tmp_path / "plugins", "0.1.0-preview.3", sessions, Vault(Fernet.generate_key().decode()))
    archive = manager.packages.inbox / "test.mtp"
    package(archive)
    assert manager.install(archive.name)["api_version"] == 2

    async def scenario():
        view = await manager.enable(MANIFEST["id"])
        assert view["runtime_status"] == "running"
        assert view["registrations"][0]["identifier"] == "example.v2-test/search"
        class InternalAction(BaseModel):
            kind: str
            query: str
            task_id: str
            runtime_metadata: dict
            optional_field: str | None = None

        action = InternalAction(kind="PluginAction_internal", query="hello", task_id="private-task", runtime_metadata={"private": "metadata"})
        public_fields = frozenset(manager.registry.get("example.v2-test/search").metadata["input_schema"]["properties"])
        public_arguments = public_plugin_tool_arguments(action, public_fields)
        assert public_arguments == {"query": "hello"}
        assert public_plugin_tool_arguments(action, public_fields | {"optional_field"}) == {"query": "hello"}
        assert await manager.invoke_tool("example.v2-test/search", public_arguments) == "result: hello"
        with pytest.raises(Exception):
            await manager.invoke_tool("example.v2-test/search", {**public_arguments, "kind": action.kind})
        assert manager.enable_recommended_tools(MANIFEST["id"]) == {"code_worker": ["example.v2-test/search"]}
        assert [tool.identifier for tool in manager.agent_tools("code_worker")] == ["example.v2-test/search"]
        assert manager.agent_tools("issue_analyzer") == []
        with pytest.raises(Exception, match="Invalid Agent Tool selection"):
            manager.set_agent_tools("issue_analyzer", ["example.v2-test/search"])
        result = await manager.invoke_tool("example.v2-test/search", {"query": "hello"})
        assert result == "result: hello"
        with pytest.raises(Exception, match="required|query"):
            await manager.invoke_tool("example.v2-test/search", {})
        await manager.disable(MANIFEST["id"])
        assert manager.registry.list() == []
        await manager.stop()

    try:
        asyncio.run(scenario())
    finally:
        engine.dispose()


@pytest.mark.parametrize("size", [80 * 1024, 1024 * 1024 - 8192])
def test_isolated_response_above_default_stream_limit_keeps_channel_usable(tmp_path, size):
    engine, sessions = database(f"sqlite:///{tmp_path / 'large-response.db'}")
    manager = PluginManager(tmp_path / "plugins", "0.1.0-preview.3", sessions, Vault(Fernet.generate_key().decode()))
    archive = manager.packages.inbox / "large-response.mtp"
    source = '''
def read(size: int) -> str:
    return "x" * size

def register(api):
    api.register_tool("read", read, description="Return a bounded test response")
'''
    package(archive, source=source)
    manager.install(archive.name)

    async def scenario():
        try:
            await manager.enable(MANIFEST["id"])
            result = await manager.invoke_tool("example.v2-test/read", {"size": size})
            assert result == "x" * size
            assert await manager.invoke_tool("example.v2-test/read", {"size": 8}) == "x" * 8
        finally:
            await manager.stop()

    try:
        asyncio.run(scenario())
    finally:
        engine.dispose()


def test_v2_package_rejects_legacy_capability_list(tmp_path):
    engine, sessions = database(f"sqlite:///{tmp_path / 'plugin-v2.db'}")
    manager = PluginManager(tmp_path / "plugins", "0.1.0-preview.3", sessions, Vault(Fernet.generate_key().decode()))
    archive = manager.packages.inbox / "bad.mtp"
    package(archive, {**MANIFEST, "capabilities": ["task.read"]})
    with pytest.raises(PluginPackageError, match="schema validation"):
        manager.packages.validate(archive)
    engine.dispose()


@pytest.mark.parametrize("unsafe", ["traversal", "symlink", "case_collision"])
def test_v2_package_rejects_unsafe_archive_members(tmp_path, unsafe):
    engine, sessions = database(f"sqlite:///{tmp_path / 'unsafe.db'}")
    manager = PluginManager(tmp_path / "plugins", "0.1.0-preview.3", sessions, Vault(Fernet.generate_key().decode()))
    archive = manager.packages.inbox / "unsafe.mtp"
    package(archive)
    with zipfile.ZipFile(archive, "a") as bundle:
        if unsafe == "traversal":
            bundle.writestr("../escape.py", "print('bad')")
        elif unsafe == "symlink":
            link = zipfile.ZipInfo("src/example/link")
            link.create_system = 3
            link.external_attr = (stat.S_IFLNK | 0o777) << 16
            bundle.writestr(link, "../../outside")
        else:
            bundle.writestr("src/example/MAIN.py", "print('collision')")
    try:
        with pytest.raises(PluginPackageError):
            manager.packages.validate(archive)
        assert not (manager.packages.installed / MANIFEST["id"]).exists()
    finally:
        engine.dispose()


def test_github_core_client_policy_privilege_and_replay(tmp_path):
    engine, sessions = database(f"sqlite:///{tmp_path / 'github-client.db'}")
    manager = PluginManager(tmp_path / "plugins", "0.1.0-preview.3", sessions, Vault(Fernet.generate_key().decode()))
    calls = []

    class GitHub:
        async def issue_context(self, installation_id, repo, number):
            calls.append(("read", installation_id, repo, number))
            return {"issue": {"number": number}}

        async def comment(self, installation_id, repo, number, body):
            calls.append(("write", installation_id, repo, number, body))
            return {"id": 42, "html_url": "https://example.test/comments/42"}

    github = GitHub()
    processor = TaskProcessor(sessions, manager.vault, object())
    processor.app_client = lambda: github
    manager.controller = processor
    with sessions.begin() as db:
        db.add(Repository(full_name="owner/repo", installation_id=7, data={}))
        task = Task(kind="issue", repository="owner/repo", number=3, event="issues.opened", delivery_id="github-client-v2", status="waiting_for_owner", data={})
        db.add(task)
        db.flush()
        task_id = task.id

    async def scenario():
        assert (await manager._v2_core_call("example.trusted", "github.issue.get", {"task_id": task_id}))["issue"]["number"] == 3
        request = {"task_id": task_id, "body": "Public comment", "invocation_id": "stable-invocation-1"}
        with pytest.raises(Exception, match="owner-approved"):
            await manager._v2_core_call("example.trusted", "github.comment", request)
        assert not any(call[0] == "write" for call in calls)
        first = await manager._v2_core_call("example.trusted", "github.privileged.comment", request)
        second = await manager._v2_core_call("example.trusted", "github.privileged.comment", request)
        assert first == second == {"id": "42", "html_url": "https://example.test/comments/42"}
        assert len([call for call in calls if call[0] == "write"]) == 1
        with sessions.begin() as db:
            task = db.get(Task, task_id)
            task.status = "running"
            task.data = {**task.data, "owner_decision_action": "implement"}
        await manager._v2_core_call("example.trusted", "github.comment", {**request, "invocation_id": "stable-invocation-2"})
        assert len([call for call in calls if call[0] == "write"]) == 2

    try:
        asyncio.run(scenario())
        with sessions() as db:
            outbox = db.query(Outbox).all()
            assert len(outbox) == 2 and all(row.status == "completed" for row in outbox)
            timeline = db.query(Timeline).filter(Timeline.task_id == task_id).all()
            assert any(row.kind == "plugin_github_write_completed" for row in timeline)
            assert "Public comment" not in json.dumps([row.data for row in timeline])
            assert "Public comment" not in json.dumps([row.data for row in outbox])
    finally:
        engine.dispose()


def test_plugin_sandbox_provider_selected_in_real_task_path(tmp_path):
    engine, sessions = database(f"sqlite:///{tmp_path / 'sandbox-provider.db'}")
    manager = PluginManager(tmp_path / "plugins", "0.1.0-preview.3", sessions, Vault(Fernet.generate_key().decode()))
    manifest = {**MANIFEST, "id": "example.sandbox-test", "entrypoint": {"python": "sandbox_plugin.main"}}
    source = '''
files = {}

def sandbox(context, payload):
    action = payload["action"]
    if action == "create":
        return {"id": payload["task_id"]}
    if action == "write_file":
        files[(payload["sandbox"], payload["path"])] = payload["content"]
        return {}
    if action == "read_file":
        return {"content": files[(payload["sandbox"], payload["path"])]}
    if action == "exec":
        return {"exit_code": 0, "output": "test passed", "truncated": False}
    if action == "destroy":
        files.clear()
        return {}
    raise ValueError("Unknown sandbox action")

def register(api):
    api.register_sandbox_provider("worker", sandbox, config_schema={"type": "object", "properties": {}})
'''
    archive = manager.packages.inbox / "sandbox.mtp"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("manifest.yaml", json.dumps(manifest))
        bundle.writestr("src/sandbox_plugin/__init__.py", "")
        bundle.writestr("src/sandbox_plugin/main.py", source)
    manager.install(archive.name)
    with sessions.begin() as db:
        db.add(Config(id="sandbox", data={"provider": "example.sandbox-test/worker", "base_url": "http://127.0.0.1:8123", "profile": "python-default"}))

    async def scenario():
        await manager.enable(manifest["id"])
        processor = TaskProcessor(sessions, manager.vault, SimpleNamespace(workspace_root=str(tmp_path)), plugins=manager)
        sandbox = processor.sandbox()
        sandbox_id = await sandbox.create("task-one", 300)
        await sandbox.write_file(sandbox_id, "src/file.txt", "example")
        assert await sandbox.read_file(sandbox_id, "src/file.txt") == "example"
        assert (await sandbox.exec(sandbox_id, "npm test", 20))["output"] == "test passed"
        with pytest.raises(ValueError, match="Unsafe path"):
            await sandbox.write_file(sandbox_id, "../escape.txt", "bad")
        await sandbox.destroy(sandbox_id)
        await manager.disable(manifest["id"])
        with pytest.raises(Exception, match="registered"):
            processor.sandbox()

    try:
        asyncio.run(scenario())
    finally:
        engine.dispose()


def test_provider_cannot_relabel_manifest_secret_as_plaintext(tmp_path):
    engine, sessions = database(f"sqlite:///{tmp_path / 'provider-secret.db'}")
    manager = PluginManager(tmp_path / "plugins", "0.1.0-preview.3", sessions, Vault(Fernet.generate_key().decode()))
    source = '''
def endpoint(context, payload):
    return {"base_url": "https://models.example/v1", "api_key": context.config["api_key"]}

def register(api):
    api.register_model_provider("unsafe", endpoint, config_schema={"type": "object", "properties": {"api_key": {"type": "string", "secret": False}}}, models=["m"])
'''
    archive = manager.packages.inbox / "provider-secret.mtp"
    package(archive, {**MANIFEST, "id": "example.provider-secret"}, source)
    manager.install(archive.name)
    manager.configure("example.provider-secret", {"api_key": "fake-secret"})
    try:
        with pytest.raises(Exception, match="same type and secret status"):
            asyncio.run(manager.enable("example.provider-secret"))
        assert "example.provider-secret" not in manager.processes
        assert manager.registry.list("provider") == []
    finally:
        engine.dispose()


def test_isolated_plugin_can_read_github_only_through_core_client(tmp_path):
    engine, sessions = database(f"sqlite:///{tmp_path / 'github-ipc.db'}")
    manager = PluginManager(tmp_path / "plugins", "0.1.0-preview.3", sessions, Vault(Fernet.generate_key().decode()))
    source = '''
async def issue(context, task_id: str) -> str:
    result = await context.call_core("github.issue.get", {"task_id": task_id})
    return result["issue"]["title"]

def register(api):
    api.register_tool("issue_title", issue, description="Read the current issue")
'''
    archive = manager.packages.inbox / "github-ipc.mtp"
    package(archive, {**MANIFEST, "id": "example.github-ipc"}, source)
    manager.install(archive.name)
    with sessions.begin() as db:
        db.add(Repository(full_name="owner/repo", installation_id=7, data={}))
        task = Task(kind="issue", repository="owner/repo", number=9, event="issues.opened", delivery_id="github-ipc-v2", status="running", data={})
        db.add(task)
        db.flush()
        task_id = task.id

    class GitHub:
        async def issue_context(self, installation_id, repo, number):
            assert (installation_id, repo, number) == (7, "owner/repo", 9)
            return {"issue": {"title": "Use public Core API"}}

    processor = TaskProcessor(sessions, manager.vault, object())
    processor.app_client = GitHub
    manager.controller = processor

    async def scenario():
        await manager.enable("example.github-ipc")
        assert await manager.invoke_tool("example.github-ipc/issue_title", {"task_id": task_id}) == "Use public Core API"
        await manager.stop()

    try:
        asyncio.run(scenario())
    finally:
        engine.dispose()


def test_v2_in_process_uses_same_sdk_registration(tmp_path):
    engine, sessions = database(f"sqlite:///{tmp_path / 'in-process.db'}")
    manager = PluginManager(tmp_path / "plugins", "0.1.0-preview.3", sessions, Vault(Fernet.generate_key().decode()))
    manifest = {**MANIFEST, "id": "example.in-process", "runtime": {"default": "in_process", "supported": ["isolated", "in_process"]}}
    archive = manager.packages.inbox / "in-process.mtp"
    package(archive, manifest)
    manager.install(archive.name)

    async def scenario():
        view = await manager.enable(manifest["id"])
        assert view["runtime_mode"] == "in_process"
        assert await manager.invoke_tool("example.in-process/search", {"query": "hello"}) == "result: hello"
        await manager.disable(manifest["id"])
        assert manager.registry.list() == []

    try:
        asyncio.run(scenario())
    finally:
        engine.dispose()


def test_external_review_wait_resume_and_core_review_flow(tmp_path):
    engine, sessions = database(f"sqlite:///{tmp_path / 'external-review.db'}")
    manager = PluginManager(tmp_path / "plugins", "0.1.0-preview.3", sessions, Vault(Fernet.generate_key().decode()))
    manifest = {**MANIFEST, "id": "example.review-test", "entrypoint": {"python": "review_plugin.main"}}
    source = '''
def review(context, payload):
    return {"action": "wait"}

async def resume(context, task_id: str, invocation_id: str, head_sha: str) -> str:
    verdict = {"head_sha": head_sha, "verdict": "approved", "summary": "Parser fix is correct", "risk": "low", "blocking_issues": [], "suggestions": []}
    result = await context.call_core("workflow.resume", {"task_id": task_id, "invocation_id": invocation_id, "result": verdict})
    return result["status"]

def register(api):
    api.register_hook("pr.review", review)
    api.register_tool("resume", resume, description="Submit the completed external review")
'''
    archive = manager.packages.inbox / "review.mtp"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("manifest.yaml", json.dumps(manifest))
        bundle.writestr("src/review_plugin/__init__.py", "")
        bundle.writestr("src/review_plugin/main.py", source)
    manager.install(archive.name)
    with sessions.begin() as db:
        task = Task(kind="pull_request", repository="owner/repo", number=5, event="pull_request.opened", delivery_id="review-v2", status="running", data={})
        db.add(task)
        db.flush()
        task_id = task.id

    head_sha = "abcdef0123456789"

    class GitHub:
        reviews = []

        async def repository_guidance(self, *args):
            return ""

        async def pull_context(self, *args):
            return {
                "pull": {"title": "Fix parser bug", "body": "Correct the parser behavior", "draft": False, "user": {"login": "alice", "type": "User"}, "head": {"sha": head_sha}, "base": {"ref": "main"}},
                "files": [{"filename": "src/parser.py", "patch": "@@ -1 +1 @@\n-bad\n+good", "status": "modified"}],
                "commits": [{"sha": head_sha}], "checks": {"check_runs": []}, "statuses": {"state": "success", "statuses": []},
            }

        async def review(self, _installation, _repo, _number, sha, event, _body, _comments):
            self.reviews.append((sha, event))
            return {"id": 1, "html_url": "https://example.test/review/1"}

    github = GitHub()

    async def scenario():
        await manager.enable(manifest["id"])
        processor = TaskProcessor(sessions, manager.vault, object(), plugins=manager)
        async def no_llm(*args):
            raise AssertionError("Core pr_reviewer must not run after valid plugin replacement")
        processor.structured_agent = no_llm
        await processor.process_pull(task_id, github, 7, "owner/repo", 5, {"default_branch": "main"})
        with sessions() as db:
            waiting = db.get(Task, task_id)
            assert waiting.status == "waiting_for_plugin"
            invocation_id = waiting.data["plugin_waiting"]["invocation_id"]
        with pytest.raises(Exception, match="stale"):
            await manager.invoke_tool("example.review-test/resume", {"task_id": task_id, "invocation_id": invocation_id, "head_sha": "0000000"})
        assert await manager.invoke_tool("example.review-test/resume", {"task_id": task_id, "invocation_id": invocation_id, "head_sha": head_sha}) == "queued"
        await processor.process_pull(task_id, github, 7, "owner/repo", 5, {"default_branch": "main"})
        assert github.reviews == [(head_sha, "APPROVE")]
        with sessions() as db:
            assert db.get(Task, task_id).status == "reviewed"
        await manager.stop()

    try:
        asyncio.run(scenario())
    finally:
        engine.dispose()


def test_v2_upgrade_migrates_config_and_retains_data(tmp_path):
    engine, sessions = database(f"sqlite:///{tmp_path / 'upgrade.db'}")
    manager = PluginManager(tmp_path / "plugins", "0.1.0-preview.3", sessions, Vault(Fernet.generate_key().decode()))
    archive = manager.packages.inbox / "initial.mtp"
    package(archive)
    manager.install(archive.name)
    manager.configure(MANIFEST["id"], {"prefix": "custom", "api_key": "secret-local-value"})
    next_manifest = {
        **MANIFEST,
        "version": "0.2.0-dev",
        "config_schema": {
            "type": "object",
            "properties": {"label": {"type": "string", "default": "new"}, "api_key": {"type": "string", "secret": True}},
            "additionalProperties": False,
        },
    }
    next_source = '''
def search(context, query: str) -> str:
    return context.config["label"] + ": " + query

def register(api):
    api.register_tool("search", search, description="Search after upgrade")

def migrate_config(old_config, old_version, new_version):
    return {"label": old_config["prefix"], "api_key": old_config["api_key"]}

def on_upgrade(context, old_version, new_version):
    (context.data_dir / "upgraded.txt").write_text(old_version + " -> " + new_version, encoding="utf-8")
'''
    upgraded = manager.packages.inbox / "next.mtp"
    package(upgraded, next_manifest, next_source)

    async def scenario():
        await manager.enable(MANIFEST["id"])
        view = await manager.upgrade(upgraded.name)
        assert view["enabled"] and view["runtime_status"] == "running"
        assert view["config"] == {"label": "custom", "api_key": "********"}
        assert await manager.invoke_tool("example.v2-test/search", {"query": "hello"}) == "custom: hello"
        assert (manager.packages.root / "data" / MANIFEST["id"] / "upgraded.txt").read_text(encoding="utf-8") == "0.1.0-dev -> 0.2.0-dev"
        await manager.stop()

    try:
        asyncio.run(scenario())
    finally:
        engine.dispose()


def test_hook_pipeline_priority_validation_and_cancel():
    registry = PluginRegistry()
    registry.register_plugin("example.second", [{"kind": "hook", "name": "issue.analysis_prompt", "priority": 20}])
    registry.register_plugin("example.first", [{"kind": "hook", "name": "issue.analysis_prompt", "priority": 10}])
    registry.register_plugin("example.last", [{"kind": "hook", "name": "issue.analysis_prompt", "priority": 20}])
    seen = []

    async def invoke(registration, payload, invocation_id, timeout):
        seen.append((registration.plugin_id, payload["prompt"], invocation_id))
        if registration.plugin_id == "example.first":
            return {"action": "modify", "payload": {**payload, "prompt": "updated"}}
        if registration.plugin_id == "example.second":
            return {"action": "cancel"}
        return {"action": "continue"}

    result = asyncio.run(registry.dispatch_hook("issue.analysis_prompt", {"task_id": "task-1", "repository": "owner/repo", "prompt": "original"}, invoke))
    assert result.action == "cancel"
    assert [item[:2] for item in seen] == [("example.first", "original"), ("example.second", "updated")]
    assert result.original["prompt"] == "original" and result.payload["prompt"] == "updated"
    assert result.steps[0]["input"]["prompt"] == "original" and result.steps[0]["output"]["prompt"] == "updated"


def test_only_retry_safe_hook_retries_with_same_invocation_id():
    registry = PluginRegistry()
    registry.register_plugin("example.retry", [
        {"kind": "hook", "name": "task.started"},
        {"kind": "hook", "name": "task.finally"},
    ])
    seen = []

    async def invoke(registration, payload, invocation_id, timeout):
        seen.append((registration.name, invocation_id))
        raise TimeoutError("simulate missing acknowledgement")

    started = asyncio.run(registry.dispatch_hook("task.started", {"task_id": "t"}, invoke))
    finalized = asyncio.run(registry.dispatch_hook("task.finally", {"task_id": "t", "status": "failed", "attempt": 1}, invoke))
    assert len([name for name, _ in seen if name == "task.started"]) == 2
    assert seen[0][1] == seen[1][1]
    assert len([name for name, _ in seen if name == "task.finally"]) == 1
    assert started.steps[0]["attempts"] == 2
    assert finalized.steps[0]["attempts"] == 1


def test_versioned_service_rejects_mismatched_consumer(tmp_path):
    engine, sessions = database(f"sqlite:///{tmp_path / 'service-version.db'}")
    manager = PluginManager(tmp_path / "plugins", "0.1.0-preview.3", sessions, Vault(Fernet.generate_key().decode()))
    archive = manager.packages.inbox / "service.mtp"
    package(archive)
    manager.install(archive.name)
    manager.registry.register_plugin(MANIFEST["id"], [{"kind": "service", "name": "search", "version": "1.2.0"}])

    async def invoke(identifier, arguments):
        return {"identifier": identifier, "input": arguments}

    manager.invoke_service = invoke
    try:
        result = asyncio.run(manager._v2_core_call(MANIFEST["id"], "service.call", {"service_id": "example.v2-test/search", "version": "1.2.0", "input": {"q": "hello"}}))
        assert result["input"] == {"q": "hello"}
        with pytest.raises(Exception, match="version"):
            asyncio.run(manager._v2_core_call(MANIFEST["id"], "service.call", {"service_id": "example.v2-test/search", "version": "2.0.0"}))
        with pytest.raises(Exception, match="version"):
            manager.registry.register_plugin("example.invalid", [{"kind": "service", "name": "search", "version": "latest"}])
    finally:
        engine.dispose()


def test_required_and_optional_plugin_dependencies(tmp_path):
    engine, sessions = database(f"sqlite:///{tmp_path / 'dependencies.db'}")
    manager = PluginManager(tmp_path / "plugins", "0.1.0-preview.3", sessions, Vault(Fernet.generate_key().decode()))
    base = {**MANIFEST, "id": "example.base"}
    required = {**MANIFEST, "id": "example.required", "dependencies": [{"id": base["id"], "version": base["version"], "requirement": "required"}]}
    optional = {**MANIFEST, "id": "example.optional", "dependencies": [{"id": "example.absent", "version": "2.0.0", "requirement": "optional"}]}
    for name, manifest in (("base", base), ("required", required), ("optional", optional)):
        archive = manager.packages.inbox / f"{name}.mtp"
        package(archive, manifest)
        manager.install(archive.name)

    async def scenario():
        with pytest.raises(Exception, match="not running"):
            await manager.enable(required["id"])
        assert (await manager.enable(optional["id"]))["runtime_status"] == "running"
        await manager.enable(base["id"])
        assert (await manager.enable(required["id"]))["runtime_status"] == "running"
        await manager.stop()

    try:
        asyncio.run(scenario())
    finally:
        engine.dispose()


@pytest.mark.parametrize("failure", ["migration", "on_upgrade"])
def test_failed_upgrade_retains_config_and_data_without_auto_rollback(tmp_path, failure):
    engine, sessions = database(f"sqlite:///{tmp_path / 'upgrade-failure.db'}")
    manager = PluginManager(tmp_path / "plugins", "0.1.0-preview.3", sessions, Vault(Fernet.generate_key().decode()))
    first = manager.packages.inbox / "first.mtp"
    package(first)
    manager.install(first.name)
    manager.configure(MANIFEST["id"], {"prefix": "owner-value", "api_key": "fake-secret"})
    data_dir = manager.packages.root / "data" / MANIFEST["id"]
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "keep.txt").write_text("keep", encoding="utf-8")
    upgraded = manager.packages.inbox / "upgrade.mtp"
    next_source = '''
def search(context, query: str) -> str:
    return query

def register(api):
    api.register_tool("search", search, description="Search")

def migrate_config(old_config, old_version, new_version):
    FAILURE
    return old_config

def on_upgrade(context, old_version, new_version):
    (context.data_dir / "attempted.txt").write_text("attempted", encoding="utf-8")
    UPGRADE_FAILURE
'''.replace("UPGRADE_FAILURE", 'raise ValueError("upgrade blocked")' if failure == "on_upgrade" else "pass").replace("FAILURE", 'raise ValueError("migration blocked")' if failure == "migration" else "pass")
    package(upgraded, {**MANIFEST, "version": "0.2.0-dev"}, next_source)

    async def scenario():
        await manager.enable(MANIFEST["id"])
        with pytest.raises(Exception, match="blocked"):
            await manager.upgrade(upgraded.name)
        assert MANIFEST["id"] not in manager.processes

    try:
        asyncio.run(scenario())
        record = manager._record(MANIFEST["id"])
        assert record["config"]["prefix"] == "owner-value"
        assert manager.vault.decrypt(record["secrets"]["api_key"]) == "fake-secret"
        assert record["enabled"] is False and "blocked" in record["error"]
        assert manager._manifest(MANIFEST["id"]).version == "0.2.0-dev"
        assert (data_dir / "keep.txt").read_text(encoding="utf-8") == "keep"
        assert (data_dir / "attempted.txt").exists() is (failure == "on_upgrade")
    finally:
        engine.dispose()


def test_disable_drains_inflight_invocation_before_stopping_runtime(tmp_path):
    engine, sessions = database(f"sqlite:///{tmp_path / 'draining.db'}")
    manager = PluginManager(tmp_path / "plugins", "0.1.0-preview.3", sessions, Vault(Fernet.generate_key().decode()))
    archive = manager.packages.inbox / "drain.mtp"
    package(archive)
    manager.install(archive.name)
    manager.registry.register_plugin(MANIFEST["id"], [{"kind": "tool", "name": "work", "description": "Wait for completion", "input_schema": {"type": "object", "properties": {}}}])

    class FakeProcess:
        def __init__(self):
            self.entered = asyncio.Event()
            self.release = asyncio.Event()
            self.stopped = False
        def state(self): return "running"
        async def request(self, method, params, timeout):
            self.entered.set()
            await self.release.wait()
            return "finished"
        async def stop(self): self.stopped = True

    async def scenario():
        process = FakeProcess()
        manager.processes[MANIFEST["id"]] = process
        invocation = asyncio.create_task(manager.invoke_tool("example.v2-test/work", {}))
        await process.entered.wait()
        stopping = asyncio.create_task(manager.disable(MANIFEST["id"]))
        await asyncio.sleep(0.1)
        assert not stopping.done() and not process.stopped
        assert manager.active_invocations[MANIFEST["id"]] == 1
        process.release.set()
        assert await invocation == "finished"
        await stopping
        assert process.stopped and MANIFEST["id"] not in manager.active_invocations

    try:
        asyncio.run(scenario())
    finally:
        engine.dispose()


def test_cancelled_tool_notifies_plugin_with_same_invocation_id(tmp_path):
    engine, sessions = database(f"sqlite:///{tmp_path / 'tool-cancel.db'}")
    manager = PluginManager(tmp_path / "plugins", "0.1.0-preview.3", sessions, Vault(Fernet.generate_key().decode()))
    manager.registry.register_plugin("example.cancel", [{"kind": "tool", "name": "wait", "description": "Wait", "input_schema": {"type": "object", "properties": {}}}])

    class FakeProcess:
        def __init__(self):
            self.entered = asyncio.Event()
            self.invocation_id = None
            self.cancelled_id = None
        def state(self): return "running"
        async def request(self, method, params, timeout):
            self.invocation_id = params["invocation_id"]
            self.entered.set()
            await asyncio.Event().wait()
        async def notify(self, method, params):
            assert method == "extension.cancel"
            self.cancelled_id = params["invocation_id"]

    async def scenario():
        process = FakeProcess()
        manager.processes["example.cancel"] = process
        call = asyncio.create_task(manager.invoke_tool("example.cancel/wait", {}, invocation_id="stable-tool-invocation"))
        await process.entered.wait()
        call.cancel()
        with pytest.raises(asyncio.CancelledError):
            await call
        assert process.invocation_id == process.cancelled_id == "stable-tool-invocation"
        assert manager.active_invocations == {}

    try:
        asyncio.run(scenario())
    finally:
        engine.dispose()


def test_invalid_pipeline_output_never_reaches_next_plugin():
    registry = PluginRegistry()
    registry.register_plugin("example.invalid", [{"kind": "hook", "name": "issue.analysis_prompt"}])
    registry.register_plugin("example.valid", [{"kind": "hook", "name": "issue.analysis_prompt"}])
    seen = []

    async def invoke(registration, payload, invocation_id, timeout):
        seen.append(payload["prompt"])
        if registration.plugin_id == "example.invalid":
            return {"action": "modify", "payload": {**payload, "prompt": 42}}
        return {"action": "continue"}

    result = asyncio.run(registry.dispatch_hook("issue.analysis_prompt", {"task_id": "task-1", "repository": "owner/repo", "prompt": "safe"}, invoke))
    assert seen == ["safe", "safe"]
    assert result.steps[0]["status"] == "failed"


@pytest.mark.parametrize("status", ["completed", "failed_agent", "cancelled", "failed_timeout", "failed_environment", "review_cancelled"])
def test_task_finalizer_runs_once_for_terminal_outcomes(tmp_path, status):
    engine, sessions = database(f"sqlite:///{tmp_path / 'finalizer.db'}")
    manager = PluginManager(tmp_path / "plugins", "0.1.0-preview.3", sessions, Vault(Fernet.generate_key().decode()))
    manager.registry.register_plugin("example.finalizer", [{"kind": "hook", "name": "task.finally"}])
    with sessions.begin() as db:
        task = Task(kind="issue", repository="owner/repo", number=1, event="issues.opened", delivery_id="final-" + status, status=status, attempts=1, data={})
        db.add(task)
        db.flush()
        task_id = task.id
    calls = []

    async def invoke(registration, payload, invocation_id, timeout):
        calls.append((payload["status"], invocation_id))

    manager._invoke_extension = invoke
    asyncio.run(manager.finalize_task(task_id))
    asyncio.run(manager.finalize_task(task_id))
    assert len(calls) == 1 and calls[0][0] == status
    engine.dispose()


def test_failed_task_finalizer_keeps_same_invocation_for_retry(tmp_path):
    engine, sessions = database(f"sqlite:///{tmp_path / 'finalizer-failure.db'}")
    manager = PluginManager(tmp_path / "plugins", "0.1.0-preview.3", sessions, Vault(Fernet.generate_key().decode()))
    manager.registry.register_plugin("example.finalizer", [{"kind": "hook", "name": "task.finally"}])
    with sessions.begin() as db:
        task = Task(kind="issue", repository="owner/repo", number=1, event="issues.opened", delivery_id="final-failure", status="failed_agent", attempts=1, data={})
        db.add(task)
        db.flush()
        task_id = task.id
    calls = []

    async def invoke(registration, payload, invocation_id, timeout):
        calls.append(invocation_id)
        if len(calls) == 1:
            raise RuntimeError("plugin crashed")

    manager._invoke_extension = invoke
    asyncio.run(manager.finalize_task(task_id))
    with sessions() as db:
        record = db.get(Config, f"plugin-finalizer:{task_id}:1:example.finalizer")
        assert record.data["status"] == "incomplete"
    asyncio.run(manager.finalize_task(task_id))
    assert calls[0] == calls[1]
    with sessions() as db:
        assert db.get(Config, f"plugin-finalizer:{task_id}:1:example.finalizer").data["status"] == "completed"
    engine.dispose()


@pytest.mark.parametrize("failure_point,expected_status", [
    ("runtime_config", "failed_environment"),
    ("provider", "failed_agent"),
    ("cancelled", "interrupted"),
])
def test_task_processor_runs_finalizer_on_real_terminal_paths(tmp_path, monkeypatch, failure_point, expected_status):
    engine, sessions = database(f"sqlite:///{tmp_path / 'processor-finalizer.db'}")
    vault = Vault(Fernet.generate_key().decode())
    manager = PluginManager(tmp_path / "plugins", "0.1.0-preview.3", sessions, vault)
    manager.registry.register_plugin("example.finalizer", [{"kind": "hook", "name": "task.finally"}])
    with sessions.begin() as db:
        db.add(Config(id="general", data={}))
        db.add(Config(id="github", data={"app_id": 1, "private_key": vault.encrypt("private")}))
        db.add(Repository(full_name="owner/repo", installation_id=1, data={"default_branch": "main", "additional_instructions": ""}))
        task = Task(kind="issue", repository="owner/repo", number=1, event="issues.opened", delivery_id=f"processor-{failure_point}", data={})
        db.add(task)
        db.flush()
        task_id = task.id
    calls = []

    async def invoke(registration, payload, invocation_id, timeout):
        calls.append((payload["task_id"], payload["status"], invocation_id))

    issue_started = asyncio.Event()

    class GitHub:
        async def issue_context(self, *_):
            if failure_point == "cancelled":
                issue_started.set()
                await asyncio.Event().wait()
            return {"issue": {"title": "Fix broken login", "body": "Login fails on every attempt"}, "comments": []}

        async def repository_guidance(self, *_):
            return ""

    if failure_point == "runtime_config":
        monkeypatch.setattr("maintainer.tasks.resolve_all_agents", lambda db: (_ for _ in ()).throw(ValueError("Runtime configuration is invalid")))
    else:
        monkeypatch.setattr("maintainer.tasks.resolve_all_agents", lambda db: {})
    manager._invoke_extension = invoke
    processor = TaskProcessor(sessions, vault, SimpleNamespace(), plugins=manager)
    processor.app_client = GitHub
    try:
        if failure_point == "cancelled":
            async def cancel_running_task():
                running = asyncio.create_task(processor.process(task_id))
                await asyncio.wait_for(issue_started.wait(), 5)
                running.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await running

            asyncio.run(cancel_running_task())
        else:
            asyncio.run(processor.process(task_id))
        asyncio.run(processor.process(task_id))
        with sessions() as db:
            assert db.get(Task, task_id).status == expected_status
            assert len(list(db.query(Timeline).filter(Timeline.task_id == task_id, Timeline.kind == "plugin_finalizer_completed"))) == 1
        assert len(calls) == 1
        assert calls[0][:2] == (task_id, expected_status)
        if failure_point == "provider":
            with sessions.begin() as db:
                db.get(Task, task_id).status = "queued"
            asyncio.run(processor.process(task_id))
            with sessions() as db:
                assert db.get(Task, task_id).attempts == 2
                assert len(list(db.query(Timeline).filter(Timeline.task_id == task_id, Timeline.kind == "plugin_finalizer_completed"))) == 2
            assert len(calls) == 2 and calls[0][2] != calls[1][2]
    finally:
        engine.dispose()
