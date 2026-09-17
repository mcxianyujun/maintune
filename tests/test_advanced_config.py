import asyncio
import json
import sqlite3
import subprocess
import sys
import time

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select, text

from maintainer.api import create_app
from maintainer.config import ResolvedAgentConfig, resolve_agent_config
from maintainer.db import Agent, Config, ConfigAudit, Provider, Repository, RuntimeSnapshot, Task, Timeline, database
from maintainer.providers import openai_compatible_parameters
from maintainer.runtime import AgentHardLimitReached, AgentLoopDetected, AgentStepLimitReached, AgentTaskTimeout, ModelRequestTimeout, RuntimeResult, StepBudgetController, ToolCallTimeout, agent_task, model_request, tool_call
from maintainer.sandboxes import LocalSandbox
from maintainer.schemas import AgentInput, GeneralSettings, IssueAnalysis, ModelDefinition, ProviderInput, ReviewVerdict
from maintainer.security import Settings
from maintainer.tasks import TaskProcessor


def model_definition(**overrides):
    value = {
        "id": "reasoner",
        "display_name": "Reasoner",
        "enabled": True,
        "capabilities": {
            "supports_reasoning": True,
            "supports_reasoning_effort": True,
            "supports_reasoning_budget": True,
            "supports_temperature": True,
            "supports_top_p": True,
            "supports_max_output_tokens": True,
        },
        "defaults": {
            "reasoning": {"mode": "auto", "effort": "low", "budget": "auto"},
            "generation": {"temperature": 0.3, "top_p": 0.9, "max_output_tokens": 1000},
            "request_timeout": 111,
            "extra_params": {"future_parameter": True, "temperature": 1.9},
        },
    }
    value.update(overrides)
    return value


def test_v4_migration_preserves_legacy_data_and_is_idempotent(tmp_path):
    path = tmp_path / "legacy.db"
    connection = sqlite3.connect(path)
    connection.executescript("""
        CREATE TABLE config (id VARCHAR(100) PRIMARY KEY, data JSON NOT NULL);
        CREATE TABLE providers (id VARCHAR(36) PRIMARY KEY, data JSON NOT NULL, encrypted_key TEXT);
        CREATE TABLE agents (id VARCHAR(64) PRIMARY KEY, data JSON NOT NULL);
        CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at FLOAT NOT NULL);
        INSERT INTO schema_migrations VALUES (2, 1);
    """)
    general = {"model": {"provider": "p1", "model": "legacy-model"}, "system_prompt": "keep this prompt", "max_steps": 20, "timeout": 120}
    provider = {"name": "Legacy", "type": "openai-compatible", "base_url": "https://models.example/v1", "models": ["legacy-model"]}
    agent = {"name": "Worker", "identifier": "worker", "enabled": True, "description": "keep", "system_prompt": "keep agent prompt", "model": None}
    connection.execute("INSERT INTO config VALUES (?, ?)", ("general", json.dumps(general)))
    connection.execute("INSERT INTO providers VALUES (?, ?, ?)", ("p1", json.dumps(provider), "encrypted-secret"))
    connection.execute("INSERT INTO agents VALUES (?, ?)", ("worker", json.dumps(agent)))
    connection.commit(); connection.close()

    engine, sessions = database(f"sqlite:///{path}")
    with sessions() as db:
        migrated_general = db.get(Config, "general").data
        migrated_provider = db.get(Provider, "p1")
        migrated_agent = db.get(Agent, "worker").data
        assert migrated_general["system_prompt"] == "keep this prompt"
        assert migrated_general["steps"]["fixed_steps"] == 20
        assert migrated_general["timeouts"] == {"model_request": 120, "tool_call": 120, "agent_task": 120, "sandbox_ttl": 3600}
        assert migrated_provider.data["models"][0]["id"] == "legacy-model"
        assert migrated_provider.encrypted_key == "encrypted-secret"
        assert migrated_agent["system_prompt"] == "keep agent prompt" and migrated_agent["runtime"] == {}
    engine.dispose()

    engine, sessions = database(f"sqlite:///{path}")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM schema_migrations WHERE version=3")).scalar_one() == 1
        assert connection.execute(text("SELECT COUNT(*) FROM schema_migrations WHERE version=4")).scalar_one() == 1
    engine.dispose()


@pytest.fixture
def configured_app(tmp_path):
    settings = Settings(admin_token="a" * 40, encryption_key=Fernet.generate_key().decode(), database_url=f"sqlite:///{tmp_path / 'advanced.db'}", workspace_root=str(tmp_path / "workspaces"), plugin_root=str(tmp_path / "plugins"))
    app = create_app(settings)
    with app.state.sessions.begin() as db:
        provider = Provider(id="p1", data=ProviderInput(name="P", base_url="https://models.example/v1", models=[model_definition()]).model_dump(exclude={"api_key"}), encrypted_key=app.state.vault.encrypt("provider-key"))
        db.add(provider)
        db.get(Config, "general").data = GeneralSettings.model_validate({
            "model": {"provider": "p1", "model": "reasoner"}, "system_prompt": "main",
            "reasoning": {"mode": "off", "effort": "medium", "budget": 4000},
            "generation": {"temperature": 0.2, "top_p": None, "max_output_tokens": None},
            "steps": {"mode": "auto", "fixed_steps": None, "soft_limit": None, "hard_limit": None, "extension": 30, "loop_threshold": 4},
            "timeouts": {"model_request": None, "tool_call": 600, "agent_task": 1800, "sandbox_ttl": 3600},
        }).model_dump()
        worker = db.get(Agent, "code_worker")
        current = AgentInput.model_validate(worker.data).model_dump()
        current["runtime"] = {
            **current["runtime"],
            "reasoning": {"mode": "on", "effort": "extra_high", "budget": "unset"},
            "generation": {"temperature": None, "top_p": 0.7, "max_output_tokens": 2000},
            "timeouts": {"model_request": 222, "tool_call": 900, "agent_task": 3600, "sandbox_ttl": None},
        }
        worker.data = AgentInput.model_validate(current).model_dump()
    return app


def test_effective_config_inheritance_overrides_and_auto_budgets(configured_app):
    with configured_app.state.sessions() as db:
        main = resolve_agent_config(db, "main")
        worker = resolve_agent_config(db, "code_worker")
    assert (main.soft_step_limit, main.hard_step_limit) == (60, 120)
    assert main.reasoning_mode == "off" and main.reasoning_effort == "medium" and main.reasoning_budget == 4000
    assert main.temperature == 0.2 and main.top_p == 0.9 and main.max_output_tokens == 1000
    assert main.model_timeout == 111
    assert (worker.soft_step_limit, worker.hard_step_limit, worker.step_extension, worker.loop_threshold) == (100, 200, 30, 4)
    assert worker.reasoning_mode == "on" and worker.reasoning_effort == "extra_high" and worker.reasoning_budget is None
    assert worker.temperature == 0.2 and worker.top_p == 0.7 and worker.max_output_tokens == 2000
    assert (worker.model_timeout, worker.tool_timeout, worker.task_timeout, worker.sandbox_ttl) == (222, 900, 3600, 3600)


def resolved(**changes):
    data = {
        "agent": "main", "provider": "p", "provider_name": "P", "provider_type": "openai-compatible", "base_url": "https://example/v1",
        "model": "m", "model_display_name": "M", "system_prompt": "system",
        "capabilities": {"supports_reasoning": True, "supports_reasoning_effort": True, "supports_reasoning_budget": True, "supports_temperature": True, "supports_top_p": True, "supports_max_output_tokens": True},
        "reasoning_mode": "on", "reasoning_effort": "extra_high", "reasoning_budget": 8000,
        "temperature": 0.25, "top_p": 0.8, "max_output_tokens": 4096,
        "extra_params": {"future": True, "temperature": 1.8, "messages": ["untrusted"], "max_tokens": 1},
        "steps_mode": "auto", "soft_step_limit": 60, "hard_step_limit": 120, "step_extension": 20, "loop_threshold": 3,
        "model_timeout": 300, "tool_timeout": 600, "task_timeout": 1800, "sandbox_ttl": 3600,
    }
    data.update(changes)
    return ResolvedAgentConfig.model_validate(data)


def test_provider_adapter_capabilities_mapping_and_precedence():
    parameters = openai_compatible_parameters(resolved())
    assert parameters == {"future": True, "reasoning": {"enabled": True}, "reasoning_effort": "xhigh", "reasoning_budget": 8000, "temperature": 0.25, "top_p": 0.8, "max_tokens": 4096}
    disabled = {key: False for key in resolved().capabilities}
    assert openai_compatible_parameters(resolved(capabilities=disabled)) == {"future": True}
    assert "reasoning" not in openai_compatible_parameters(resolved(reasoning_mode="auto"))
    assert openai_compatible_parameters(resolved(reasoning_mode="off"))["reasoning"] == {"enabled": False}


def test_extra_params_reject_nested_secrets_and_invalid_limits():
    with pytest.raises(ValidationError):
        ProviderInput(name="P", base_url="https://example/v1", models=[model_definition(defaults={"extra_params": {"nested": {"authorization": "secret"}}})])
    with pytest.raises(ValidationError):
        GeneralSettings.model_validate({"steps": {"mode": "auto", "soft_limit": 20, "hard_limit": 10}})
    with pytest.raises(ValidationError):
        GeneralSettings.model_validate({"generation": {"temperature": 3}})
    unsupported = model_definition(
        capabilities={},
        defaults={"reasoning": {"mode": "on"}},
    )
    with pytest.raises(ValidationError):
        ProviderInput(name="P", base_url="https://example/v1", models=[unsupported])


def test_step_budget_extension_hard_limit_and_loop_detection():
    extending = StepBudgetController(soft_limit=5, hard_limit=20, extension=15, loop_threshold=3)
    for index in range(5):
        extending.record("write_file", {"path": f"{index}.txt", "content": str(index)})
    extending.record("shell", {"command": "npm test"})
    assert extending.steps == 6 and extending.current_limit == 20
    assert [event["kind"] for event in extending.events[-2:]] == ["agent_soft_limit_reached", "agent_budget_extended"]

    bounded = StepBudgetController(soft_limit=3, hard_limit=5, extension=2, loop_threshold=3)
    for index in range(5):
        bounded.record("write_file", {"path": f"{index}.txt", "content": str(index)})
    with pytest.raises(AgentHardLimitReached):
        bounded.record("read_file", {"path": "sixth.txt"})
    assert bounded.steps == 5 and bounded.events[-1]["kind"] == "agent_hard_limit_reached"

    looping = StepBudgetController(soft_limit=10, hard_limit=20, loop_threshold=3)
    looping.record("read_file", {"path": "same"}); looping.record("read_file", {"path": "same"})
    with pytest.raises(AgentLoopDetected): looping.record("read_file", {"path": "same"})
    assert looping.steps == 2 and looping.events[-1]["kind"] == "agent_loop_detected"


def test_started_task_uses_immutable_sanitized_runtime_snapshot(configured_app):
    with configured_app.state.sessions.begin() as db:
        task = Task(kind="issue", repository="missing/repo", number=1, event="issues.opened", delivery_id="snapshot", data={})
        db.add(task); db.flush(); task_id = task.id
    processor = TaskProcessor(configured_app.state.sessions, configured_app.state.vault, configured_app.state.settings)
    asyncio.run(processor.process(task_id))
    with configured_app.state.sessions.begin() as db:
        snapshot = db.scalar(select(RuntimeSnapshot).where(RuntimeSnapshot.task_id == task_id, RuntimeSnapshot.agent_id == "main"))
        assert snapshot and snapshot.data["model"] == "reasoner"
        assert "provider-key" not in json.dumps(snapshot.data)
        timeline = list(db.scalars(select(Timeline).where(Timeline.task_id == task_id)))
        assert "provider-key" not in json.dumps([event.data for event in timeline])
        provider = db.get(Provider, "p1")
        provider.data = {**provider.data, "models": [{**model_definition(), "id": "changed"}]}
        general = db.get(Config, "general")
        general.data = {**general.data, "model": {"provider": "p1", "model": "changed"}}
    configuration, key = processor.model("main", task_id)
    assert configuration.model == "reasoner" and key == "provider-key"


def test_advanced_configuration_api_round_trip(configured_app):
    headers = {"Authorization": "Bearer " + "a" * 40}
    with TestClient(configured_app) as client:
        providers = client.get("/api/providers", headers=headers).json()
        assert providers[0]["models"][0]["defaults"]["request_timeout"] == 111
        provider_payload = {key: providers[0][key] for key in ("name", "type", "base_url", "models")}
        saved_provider = client.put(f"/api/providers/{providers[0]['id']}", headers=headers, json=provider_payload)
        assert saved_provider.status_code == 200 and saved_provider.json()["models"] == providers[0]["models"]

        settings = client.get("/api/settings", headers=headers).json()
        saved_settings = client.put("/api/settings", headers=headers, json=settings)
        assert saved_settings.status_code == 200 and saved_settings.json() == settings

        agents = client.get("/api/agents", headers=headers).json()
        worker = next(item for item in agents if item["identifier"] == "code_worker")
        saved_agent = client.put("/api/agents/code_worker", headers=headers, json=worker)
        assert saved_agent.status_code == 200 and saved_agent.json() == worker
        effective = client.get("/api/runtime-configs", headers=headers).json()["code_worker"]
        assert effective["reasoning_effort"] == "extra_high" and effective["hard_step_limit"] == 200

        original_model = provider_payload["models"][0]
        unsupported_model = {"id": "plain", "display_name": "Plain", "enabled": True, "capabilities": {}, "defaults": {}}
        provider_payload["models"].append(unsupported_model)
        assert client.put(f"/api/providers/{providers[0]['id']}", headers=headers, json=provider_payload).status_code == 200
        provider_payload["models"][0] = {**original_model, "capabilities": {}, "defaults": {}}
        assert client.put(f"/api/providers/{providers[0]['id']}", headers=headers, json=provider_payload).status_code == 422
        settings["model"]["model"] = "plain"
        settings["reasoning"]["mode"] = "on"
        response = client.put("/api/settings", headers=headers, json=settings)
        assert response.status_code == 422 and "does not support" in response.json()["detail"]


def test_agents_api_normalizes_legacy_empty_runtime_for_ui(configured_app):
    headers = {"Authorization": "Bearer " + "a" * 40}
    with configured_app.state.sessions.begin() as db:
        worker = db.get(Agent, "code_worker")
        worker.data = {**worker.data, "runtime": {}}
    with TestClient(configured_app) as client:
        worker = next(item for item in client.get("/api/agents", headers=headers).json() if item["identifier"] == "code_worker")
    assert worker["runtime"] == {
        "reasoning": {"mode": None, "effort": None, "budget": None},
        "generation": {"temperature": None, "top_p": None, "max_output_tokens": None},
        "steps": None,
        "timeouts": {"model_request": None, "tool_call": None, "agent_task": None, "sandbox_ttl": None},
    }


def test_reset_helpers_and_api_preserve_identity_prompts_secrets_and_history(configured_app):
    headers = {"Authorization": "Bearer " + "a" * 40}
    with configured_app.state.sessions.begin() as db:
        general = GeneralSettings.model_validate(db.get(Config, "general").data)
        general_data = general.model_dump()
        general_data.update({
            "system_prompt": "never reset main prompt",
            "steps": {"mode": "fixed", "fixed_steps": 9, "soft_limit": 9, "hard_limit": 9, "extension": 3, "loop_threshold": 4},
            "timeouts": {"model_request": 9, "tool_call": 8, "agent_task": 7, "sandbox_ttl": 600},
        })
        db.get(Config, "general").data = GeneralSettings.model_validate(general_data).model_dump()
        worker = AgentInput.model_validate(db.get(Agent, "code_worker").data)
        db.get(Agent, "code_worker").data = worker.model_copy(update={"system_prompt": "never reset worker prompt", "name": "Worker name", "description": "Worker description"}).model_dump()
        db.add(Config(id="github", data={"private_key": "encrypted-github", "webhook_secret": "encrypted-webhook"}))
        db.add(Config(id="email", data={"password": "encrypted-email"}))
        db.add(Repository(full_name="owner/keep", installation_id=1, data={"enabled": True}))
        db.add(Task(kind="issue", repository="owner/keep", number=1, event="x", delivery_id="keep-history", status="completed", data={"summary": "keep"}))
        secret_before = db.get(Provider, "p1").encrypted_key

    with TestClient(configured_app) as client:
        provider_before = client.get("/api/providers", headers=headers).json()[0]
        capabilities_before = provider_before["models"][0]["capabilities"]
        for scope in ("reasoning", "generation", "advanced", "all"):
            response = client.post(f"/api/providers/p1/models/reasoner/reset", headers=headers, json={"scope": scope})
            assert response.status_code == 200
        model = response.json()["provider"]["models"][0]
        assert model["id"] == "reasoner" and model["display_name"] == "Reasoner" and model["enabled"]
        assert model["capabilities"] == capabilities_before
        assert model["defaults"] == {"reasoning": {"mode": "auto", "effort": "inherit", "budget": None}, "generation": {"temperature": None, "top_p": None, "max_output_tokens": None}, "request_timeout": None, "extra_params": {}}

        for scope in ("reasoning", "generation", "budget", "timeouts", "all"):
            response = client.post("/api/settings/reset", headers=headers, json={"scope": scope})
            assert response.status_code == 200
        settings = response.json()["settings"]
        assert settings["system_prompt"] == "never reset main prompt" and settings["model"] == {"provider": "p1", "model": "reasoner"}
        assert settings["steps"] == {"mode": "auto", "fixed_steps": None, "soft_limit": None, "hard_limit": None, "extension": 20, "loop_threshold": 3}
        assert settings["timeouts"] == {"model_request": None, "tool_call": None, "agent_task": None, "sandbox_ttl": None}
        assert response.json()["resolved"]["soft_step_limit"] == 60 and response.json()["resolved"]["task_timeout"] == 1800

        for scope in ("reasoning", "generation", "steps", "timeouts", "all"):
            response = client.post("/api/agents/code_worker/reset", headers=headers, json={"scope": scope})
            assert response.status_code == 200
        agent = response.json()["agent"]
        assert {key: agent[key] for key in ("name", "description", "system_prompt")} == {"name": "Worker name", "description": "Worker description", "system_prompt": "never reset worker prompt"}
        assert agent["model"] is None and agent["runtime"]["steps"] is None
        assert response.json()["resolved"]["soft_step_limit"] == 100 and response.json()["resolved"]["hard_step_limit"] == 200

    with configured_app.state.sessions() as db:
        assert db.get(Provider, "p1").encrypted_key == secret_before
        assert db.get(Config, "github").data == {"private_key": "encrypted-github", "webhook_secret": "encrypted-webhook"}
        assert db.get(Config, "email").data == {"password": "encrypted-email"}
        assert db.get(Repository, "owner/keep") and db.scalar(select(Task).where(Task.delivery_id == "keep-history"))
        audits = list(db.scalars(select(ConfigAudit).where(ConfigAudit.kind == "config_reset")))
        assert len(audits) == 14
        assert all(set(audit.data) == {"object_type", "object_id", "reset_scope"} for audit in audits)


def test_model_tool_and_task_timeouts_are_distinct():
    async def delayed():
        await asyncio.sleep(0.1)
        return "late"
    with pytest.raises(ModelRequestTimeout, match="Model request"):
        asyncio.run(model_request(delayed(), 0.01))
    with pytest.raises(ToolCallTimeout, match="Tool call"):
        asyncio.run(tool_call(delayed(), 0.01))
    with pytest.raises(AgentTaskTimeout, match="Agent task"):
        asyncio.run(agent_task(delayed(), 0.01))


def test_isolated_model_and_whole_task_timeouts_use_configured_deadlines():
    async def delayed_model():
        await asyncio.sleep(2.5)

    started = time.monotonic()
    with pytest.raises(ModelRequestTimeout):
        asyncio.run(model_request(delayed_model(), 2))
    assert 1.8 <= time.monotonic() - started < 2.5

    progress = []
    async def multi_step_task():
        for step in range(4):
            await asyncio.sleep(1.1)
            progress.append(step)

    started = time.monotonic()
    with pytest.raises(AgentTaskTimeout):
        asyncio.run(agent_task(multi_step_task(), 3))
    assert 2.8 <= time.monotonic() - started < 3.5
    assert progress == [0, 1]


def test_isolated_sandbox_command_reports_tool_timeout(tmp_path):
    sandbox = LocalSandbox(str(tmp_path / "sandboxes"))
    sandbox_id = asyncio.run(sandbox.create("timeout"))
    command = subprocess.list2cmdline([sys.executable, "-c", "import time; time.sleep(5)"])
    started = time.monotonic()
    with pytest.raises(ToolCallTimeout, match="Tool call"):
        asyncio.run(tool_call(sandbox.exec(sandbox_id, command, 2), 5))
    elapsed = time.monotonic() - started
    assert 1.5 <= elapsed < 5
    asyncio.run(sandbox.destroy(sandbox_id))


def test_resolved_auto_budget_and_timeouts_reach_worker_runtime(configured_app):
    with configured_app.state.sessions.begin() as db:
        task = Task(kind="issue", repository="owner/runtime-chain", number=4, event="issues.opened", delivery_id="runtime-chain", attempts=1, data={})
        db.add(task); db.flush(); task_id = task.id

    class Sandbox:
        def __init__(self): self.files = {}
        async def create(self, task, ttl=3600): self.ttl = ttl; return task
        async def write_file(self, sid, path, content): self.files[path] = content
        async def read_file(self, sid, path): return self.files[path]
        async def exec(self, *args): return {"exit_code": 0, "output": "passed", "truncated": False}
        async def destroy(self, *args): pass
    sandbox = Sandbox()
    seen = {}
    class Runtime:
        async def run(self, **kwargs):
            seen.update(kwargs)
            sandbox.files["a.py"] = "new"
            return RuntimeResult(text="done", total_tokens=2, steps_used=7, budget_events=[{"kind": "agent_soft_limit_reached", "steps_used": 5}, {"kind": "agent_budget_extended", "from": 5, "to": 20}])
    class GitHub:
        async def repository_snapshot(self, *args): return "base", [("a.py", b"old")]
        async def create_fix_pull_request(self, *args): return {"id": 1, "number": 2, "html_url": "https://example/pr/2"}

    processor = TaskProcessor(configured_app.state.sessions, configured_app.state.vault, configured_app.state.settings, runtime=Runtime())
    processor.sandbox = lambda: sandbox
    async def review(*args): return ReviewVerdict(verdict="approved", summary="ok", risk="low")
    processor.structured_agent = review
    asyncio.run(processor.fix_issue(task_id, GitHub(), 1, "owner/runtime-chain", 4, {"default_branch": "main", "install_command": "", "test_command": "", "lint_command": "", "build_command": "", "working_directory": ".", "additional_instructions": ""}, {"title": "bug", "body": "body"}, IssueAnalysis(status="actionable", summary="fix", risk="low", suggested_plan=["change"])))

    assert (seen["soft_step_limit"], seen["hard_step_limit"], seen["step_extension"], seen["loop_threshold"]) == (100, 200, 30, 4)
    assert (seen["model_timeout"], seen["tool_timeout"], seen["task_timeout"]) == (222, 900, 3600)
    assert sandbox.ttl == 3600
    with configured_app.state.sessions() as db:
        completed = db.scalar(select(Timeline).where(Timeline.task_id == task_id, Timeline.kind == "worker_completed"))
        assert completed.data["steps_used"] == 7
        assert db.scalar(select(Timeline).where(Timeline.task_id == task_id, Timeline.kind == "agent_budget_extended"))


@pytest.mark.parametrize("failure,event_kind", [
    (ModelRequestTimeout("model"), "model_request_timeout"),
    (ToolCallTimeout("tool"), "agent_tool_timeout"),
    (AgentTaskTimeout("task"), "agent_task_timeout"),
])
def test_timeout_failure_metadata_and_timeline_are_distinct(configured_app, failure, event_kind):
    with configured_app.state.sessions.begin() as db:
        db.add(Config(id="github", data={"app_id": 1, "private_key": configured_app.state.vault.encrypt("private")}))
        db.add(Repository(full_name="owner/runtime", installation_id=1, data={"enabled": True}))
        task = Task(kind="issue", repository="owner/runtime", number=1, event="issues.opened", delivery_id="timeout-" + event_kind, data={})
        db.add(task); db.flush(); task_id = task.id
    processor = TaskProcessor(configured_app.state.sessions, configured_app.state.vault, configured_app.state.settings)
    processor.app_client = lambda: object()
    async def fail(*args): raise failure
    processor.process_issue = fail
    asyncio.run(processor.process(task_id))
    with configured_app.state.sessions() as db:
        task = db.get(Task, task_id)
        assert task.status == "failed_environment"
        assert task.data["failure"]["exception_type"] == type(failure).__name__
        assert db.scalar(select(Timeline).where(Timeline.task_id == task_id, Timeline.kind == event_kind))
