import asyncio
import json
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, text

from .config import resolve_agent_config, resolve_all_agents
from .db import Agent, Config, ConfigAudit, Outbox, Provider, Repository, Run, Task, Timeline, Usage, WebhookDelivery, database, uid
from .github import GitHubAppClient, ingest_webhook, verify_signature
from .providers import OpenAICompatible, openai_compatible_parameters
from .policy import owner_action
from .plugin_manager import PluginManager
from .plugin_system import MAX_MESSAGE_BYTES, PluginError, PluginPackageError
from .resets import reset_agent, reset_main, reset_model
from .runtime import DiagnosticRuntime, agent_task
from .sandboxes import LocalSandbox, ShipyardConnection
from .schemas import AgentInput, DEFAULT_PROMPT, EmailSettings, GeneralSettings, GitHubSettings, ModelRef, OwnerDecision, ProviderInput, RepositoryInput, ResetInput, RunInput, SandboxSettings
from .security import Settings, Vault, authenticate
from .tasks import TaskProcessor
from . import __version__

DEFAULT_AGENTS = {
    "issue_analyzer": ("Issue 分析", "分析问题、复现条件、缺失信息与风险。", "Analyze the issue. Identify missing information, reproduction steps and technical risk. Escalate uncertainty; do not invent evidence."),
    "code_worker": ("代码修复", "复现问题，实施最小修复并运行必要测试。", "Reproduce before fixing. Make minimal changes in the assigned sandbox and report actual tests. Never claim tests you did not run."),
    "code_reviewer": ("独立代码审核", "独立检查 AI 修改的正确性、回归、安全与测试。", "Independently review correctness, regressions, compatibility, security and tests. Style preferences alone must not block changes."),
    "pr_reviewer": ("PR 审核", "审核贡献者 PR，区分阻塞问题与建议。", "Review contributor PRs. Do not modify their branch. Give actionable file and line findings. Distinguish blocking defects from optional suggestions."),
    "ci_analyzer": ("CI 分析", "定位 CI 失败原因并判断与当前修改的关联。", "Analyze actual CI logs. Separate change-related failures from infrastructure failures. Provide evidence and actionable advice."),
}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    vault = Vault(settings.encryption_key.get_secret_value())
    engine, sessions = database(settings.database_url)
    Path(settings.workspace_root).mkdir(parents=True, exist_ok=True)
    plugin_manager = PluginManager(Path(settings.plugin_root), __version__, sessions, vault)
    with sessions.begin() as db:
        if not db.get(Config, "general"):
            db.add(Config(id="general", data=GeneralSettings().model_dump()))
        if not db.get(Config, "sandbox"):
            db.add(Config(id="sandbox", data=SandboxSettings().model_dump(exclude={"api_key"})))
        if not db.get(Config, "seeded"):
            for identifier, (name, description, prompt) in DEFAULT_AGENTS.items():
                db.add(Agent(id=identifier, data=AgentInput(name=name, identifier=identifier, description=description, system_prompt=prompt).model_dump()))
            db.add(Config(id="seeded", data={"version": 1}))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Stage 1 is single-process. Never silently replay an interrupted model call.
        with sessions.begin() as db:
            for run in db.scalars(select(Run).where(Run.status == "running")):
                run.status, run.ended = "interrupted", time.time()
                run.data = {**run.data, "error": "Service restarted; inspect and retry manually"}
            for task in db.scalars(select(Task).where(Task.status == "running")):
                task.status, task.lease_until = "interrupted", None
                task.data = {**task.data, "error": "Service restarted during processing; no external action was replayed"}
                db.add(Timeline(task_id=task.id, kind="interrupted", data={"reason": "service_restart"}))
            for action in db.scalars(select(Outbox).where(Outbox.status == "executing")):
                action.status = "unknown"
                action.error = "Service restarted while external action was executing; reconciliation required"
        app.state.processor = TaskProcessor(sessions, vault, settings, event_sink=app.state.plugins.publish_task)
        await app.state.plugins.start()
        app.state.worker_stop = asyncio.Event()
        app.state.worker = asyncio.create_task(worker_loop(app))
        yield
        app.state.worker_stop.set()
        await app.state.worker
        await app.state.plugins.stop()
        engine.dispose()

    app = FastAPI(title="Maintune", version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings, app.state.sessions, app.state.vault = settings, sessions, vault
    app.state.plugins = plugin_manager
    app.state.runtime = DiagnosticRuntime()
    app.state.provider_factory = OpenAICompatible
    api = APIRouter(prefix="/api", dependencies=[Depends(authenticate)])

    async def worker_loop(app: FastAPI):
        while not app.state.worker_stop.is_set():
            with sessions() as db:
                task_id = db.scalar(select(Task.id).where(Task.status == "queued").order_by(Task.created).limit(1))
            if task_id:
                await app.state.processor.process(task_id)
                continue
            try:
                await asyncio.wait_for(app.state.worker_stop.wait(), timeout=2)
            except TimeoutError:
                pass

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError):
        # Pydantic error details normally include submitted values, including secrets.
        return JSONResponse(status_code=422, content={"detail": "Invalid request fields", "fields": [".".join(map(str, item["loc"])) for item in error.errors()]})

    @app.middleware("http")
    async def headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        if request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
        elif request.url.path == "/":
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        elif request.url.path.startswith("/assets/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response

    @app.exception_handler(Exception)
    async def internal_error(request: Request, error: Exception):
        # Do not reflect SDK exceptions, connection URLs, headers or provider bodies.
        return JSONResponse(status_code=500, content={"detail": "Internal error; check service health"})

    def get(db, cls, key):
        obj = db.get(cls, key)
        if obj is None:
            raise HTTPException(404, "Not found")
        return obj

    def provider_config(row: Provider) -> ProviderInput:
        return ProviderInput.model_validate(row.data)

    def validate_ref(db, ref: ModelRef | None):
        if ref is not None:
            provider = get(db, Provider, ref.provider)
            definition = next((item for item in provider_config(provider).models if item.id == ref.model), None)
            if not definition or not definition.enabled:
                raise HTTPException(422, "Model is not configured on provider")
            return definition
        return None

    def validate_runtime_capabilities(definition, reasoning, generation):
        if definition is None:
            return
        capabilities, conflicts = definition.capabilities, []
        if reasoning.mode in {"on", "off"} and not capabilities.supports_reasoning: conflicts.append("reasoning mode")
        if reasoning.effort not in {None, "inherit"} and not capabilities.supports_reasoning_effort: conflicts.append("reasoning effort")
        if reasoning.budget not in {None, "unset"} and not capabilities.supports_reasoning_budget: conflicts.append("reasoning budget")
        if generation.temperature is not None and not capabilities.supports_temperature: conflicts.append("temperature")
        if generation.top_p is not None and not capabilities.supports_top_p: conflicts.append("top_p")
        if generation.max_output_tokens is not None and not capabilities.supports_max_output_tokens: conflicts.append("max_output_tokens")
        if conflicts:
            raise HTTPException(422, "Selected model does not support configured overrides: " + ", ".join(conflicts))

    def validate_agent_layers(definition, general, agent=None):
        validate_runtime_capabilities(definition, general.reasoning, general.generation)
        if agent is not None:
            validate_runtime_capabilities(definition, agent.runtime.reasoning, agent.runtime.generation)

    def provider_view(p):
        return {"id": p.id, **provider_config(p).model_dump(), "api_key_masked": "••••••••" if p.encrypted_key else "", "has_key": bool(p.encrypted_key)}

    def audit_reset(db, object_type: str, object_id: str, scope: str):
        db.add(ConfigAudit(kind="config_reset", data={"object_type": object_type, "object_id": object_id, "reset_scope": scope}))

    def run_view(r):
        return {"id": r.id, "started": r.started, "ended": r.ended, "status": r.status, **r.data}

    @app.get("/healthz")
    def health():
        with engine.connect() as connection:
            schema = connection.execute(text("SELECT COALESCE(MAX(version), 1) FROM schema_migrations")).scalar_one()
        return {"status": "ok", "version": __version__, "schema": schema}

    @app.post("/webhooks/github", status_code=202)
    async def github_webhook(request: Request):
        body = await request.body()
        if len(body) > 2_000_000:
            raise HTTPException(413, "Webhook payload too large")
        delivery_id = request.headers.get("X-GitHub-Delivery", "")
        event = request.headers.get("X-GitHub-Event", "")
        if not delivery_id or len(delivery_id) > 100 or not event or len(event) > 80:
            raise HTTPException(400, "Missing GitHub delivery headers")
        with sessions() as db:
            config = db.get(Config, "github")
            secret = vault.decrypt(config.data.get("webhook_secret")) if config else ""
        if not verify_signature(body, request.headers.get("X-Hub-Signature-256"), secret):
            raise HTTPException(401, "Invalid webhook signature")
        try:
            payload = __import__("json").loads(body)
        except Exception:
            raise HTTPException(400, "Invalid JSON payload") from None
        with sessions.begin() as db:
            delivery, task, duplicate = ingest_webhook(db, delivery_id, event, body, payload)
            return {"delivery_id": delivery_id, "status": delivery.status, "task_id": task.id if task else None, "duplicate": duplicate}

    @api.get("/capabilities")
    def capabilities():
        with sessions() as db:
            github = db.get(Config, "github")
            email = db.get(Config, "email")
        return {"stage": "github-automation", "runtime": "OpenHands adapter with controlled sandbox tools", "github_automation": bool(github and github.data.get("private_key") and github.data.get("webhook_secret")), "auto_merge": True, "plugins": False, "email": bool(email and email.data.get("enabled")), "docker_sandbox": False, "openhands": "1.47.0 integrated", "version": __version__}

    def masked_config(key: str, secret_fields: tuple[str, ...]):
        with sessions() as db:
            row = db.get(Config, key)
            data = dict(row.data) if row else {}
        for field in secret_fields:
            present = bool(data.pop(field, None))
            data["has_" + field] = present
            data[field + "_masked"] = "••••••••" if present else ""
        return data

    def setup_snapshot(request: Request):
        workspace = Path(settings.workspace_root)
        storage_ready = workspace.exists() and os.access(workspace, os.W_OK)
        with sessions() as db:
            general = GeneralSettings.model_validate(get(db, Config, "general").data)
            providers_ready = bool(general.model and db.get(Provider, general.model.provider) and db.get(Provider, general.model.provider).encrypted_key)
            github = db.get(Config, "github")
            sandbox_data = get(db, Config, "sandbox").data
            sandbox = SandboxSettings.model_validate({key: value for key, value in sandbox_data.items() if key != "encrypted_key"})
            repository_count = sum(1 for row in db.scalars(select(Repository)) if row.data.get("enabled", True))
            diagnostic = db.get(Config, "setup_diagnostics")
            checks = dict(diagnostic.data.get("checks", {})) if diagnostic else {}
        steps = {
            "system": storage_ready,
            "model": providers_ready,
            "github": bool(github and github.data.get("app_id") and github.data.get("private_key") and github.data.get("webhook_secret")),
            "sandbox": sandbox.provider == "local" or bool(sandbox.base_url and get_saved_sandbox_key()),
            "repository": repository_count > 0,
            "optional_services": True,
            "diagnostics": bool(checks) and all(item.get("ok") for item in checks.values()),
        }
        return {"version": __version__, "schema": 4, "base_url": str(request.base_url).rstrip("/"), "steps": steps, "checks": checks, "complete": all(steps.values()), "repository_count": repository_count}

    def get_saved_sandbox_key():
        with sessions() as db:
            return bool(get(db, Config, "sandbox").data.get("encrypted_key"))

    async def probe_sandbox():
        with sessions() as db:
            data = get(db, Config, "sandbox").data
        if data["provider"] == "shipyard":
            return await ShipyardConnection().test(data["base_url"], vault.decrypt(data.get("encrypted_key")))
        local = LocalSandbox(settings.workspace_root)
        sandbox_id = await local.create(uid())
        try:
            await local.write_file(sandbox_id, "probe.txt", "maintainer-probe")
            if await local.read_file(sandbox_id, "probe.txt") != "maintainer-probe":
                raise ValueError("Readback mismatch")
        finally:
            await local.destroy(sandbox_id)
        return {"ok": True, "capability": "isolated file workspace; shell disabled"}

    @api.get("/github")
    def github_settings():
        return masked_config("github", ("private_key", "webhook_secret"))

    @api.put("/github")
    def write_github(body: GitHubSettings):
        with sessions.begin() as db:
            old = db.get(Config, "github")
            data = dict(old.data) if old else {}
            data.update(body.model_dump(exclude={"private_key", "webhook_secret"}))
            for name in ("private_key", "webhook_secret"):
                value = getattr(body, name)
                if value and value.get_secret_value(): data[name] = vault.encrypt(value.get_secret_value())
            if not old: db.add(Config(id="github", data=data))
            else: old.data = data
        return github_settings()

    @api.post("/github/test")
    async def test_github():
        with sessions() as db:
            row = db.get(Config, "github")
            if not row or not row.data.get("private_key"): raise HTTPException(409, "Configure GitHub App first")
            data = row.data
        try:
            installs = await GitHubAppClient(data["app_id"], vault.decrypt(data["private_key"]), data.get("api_url", "https://api.github.com")).installations()
            return {"ok": True, "installations": [{"id": x["id"], "account": x.get("account", {}).get("login")} for x in installs]}
        except Exception:
            raise HTTPException(502, "GitHub App connection failed") from None

    @api.get("/setup/status")
    def setup_status(request: Request):
        return setup_snapshot(request)

    @api.post("/setup/diagnostics")
    async def setup_diagnostics(request: Request):
        checks: dict[str, dict] = {}

        async def run_check(name, operation):
            try:
                detail = await operation()
                checks[name] = {"ok": True, "detail": detail if isinstance(detail, str) else "ready"}
            except Exception as error:
                checks[name] = {"ok": False, "detail": type(error).__name__}

        async def database_check():
            with engine.connect() as connection:
                connection.execute(text("SELECT 1")).scalar_one()
            return "schema 4"

        async def model_check():
            with sessions() as db:
                resolved = resolve_agent_config(db, "main")
                provider_row = get(db, Provider, resolved.provider)
                provider = app.state.provider_factory(provider_row.data["base_url"], vault.decrypt(provider_row.encrypted_key))
            async with asyncio.timeout(resolved.model_timeout):
                models = await provider.models()
            if resolved.model not in models:
                raise ValueError("Configured model was not listed")
            return "configured model listed"

        async def github_check():
            with sessions() as db:
                row = get(db, Config, "github"); data = row.data
            installs = await GitHubAppClient(data["app_id"], vault.decrypt(data["private_key"]), data.get("api_url", "https://api.github.com")).installations()
            if not installs:
                raise ValueError("No installations")
            return "installation available"

        async def runtime_check():
            with sessions() as db:
                resolve_agent_config(db, "main")
            __import__("openhands.sdk")
            return "OpenHands import and config resolution"

        async def repository_check():
            with sessions() as db:
                if not db.scalar(select(Repository.full_name).limit(1)):
                    raise ValueError("No repository")
            return "repository configured"

        for name, operation in (
            ("database", database_check), ("model", model_check), ("github", github_check),
            ("sandbox", probe_sandbox), ("runtime", runtime_check), ("repository", repository_check),
        ):
            await run_check(name, operation)
        with sessions.begin() as db:
            row = db.get(Config, "setup_diagnostics"); data = {"timestamp": time.time(), "checks": checks}
            if row: row.data = data
            else: db.add(Config(id="setup_diagnostics", data=data))
        return setup_snapshot(request)

    @api.get("/repositories")
    def repositories():
        with sessions() as db: return [{"full_name": r.full_name, "installation_id": r.installation_id, **r.data} for r in db.scalars(select(Repository).order_by(Repository.full_name))]

    @api.put("/repositories/{owner}/{name}")
    def write_repository(owner: str, name: str, body: RepositoryInput):
        full_name = owner + "/" + name
        if body.full_name.lower() != full_name.lower(): raise HTTPException(422, "Repository path mismatch")
        with sessions.begin() as db:
            row = db.get(Repository, full_name)
            data = body.model_dump(exclude={"full_name", "installation_id"})
            if row: row.data, row.installation_id = data, body.installation_id
            else: db.add(Repository(full_name=full_name, installation_id=body.installation_id, data=data))
        return body

    @api.delete("/repositories/{owner}/{name}", status_code=204)
    def delete_repository(owner: str, name: str):
        with sessions.begin() as db:
            row = db.get(Repository, owner + "/" + name)
            if not row: raise HTTPException(404, "Not found")
            db.delete(row)

    @api.get("/email")
    def email_settings(): return masked_config("email", ("password",))

    @api.put("/email")
    def write_email(body: EmailSettings):
        with sessions.begin() as db:
            row = db.get(Config, "email"); data = dict(row.data) if row else {}
            data.update(body.model_dump(exclude={"password"}))
            if body.password and body.password.get_secret_value(): data["password"] = vault.encrypt(body.password.get_secret_value())
            if row: row.data = data
            else: db.add(Config(id="email", data=data))
        return email_settings()

    def task_view(task, timeline=None):
        return {"id": task.id, "kind": task.kind, "repository": task.repository, "number": task.number, "event": task.event, "status": task.status, "created": task.created, "updated": task.updated, "attempts": task.attempts, **task.data, **({"timeline": [{"timestamp": x.timestamp, "kind": x.kind, "data": x.data} for x in timeline]} if timeline is not None else {})}

    @api.get("/tasks")
    def tasks():
        with sessions() as db: return [task_view(t) for t in db.scalars(select(Task).order_by(Task.created.desc()).limit(100))]

    @api.get("/tasks/{task_id}")
    def task_detail(task_id: str):
        with sessions() as db:
            task = db.get(Task, task_id)
            if not task: raise HTTPException(404, "Not found")
            timeline = list(db.scalars(select(Timeline).where(Timeline.task_id == task_id).order_by(Timeline.timestamp)))
            return task_view(task, timeline)

    @api.post("/tasks/{task_id}/decision")
    def owner_decision(task_id: str, body: OwnerDecision):
        with sessions.begin() as db:
            task = db.get(Task, task_id)
            if not task: raise HTTPException(404, "Not found")
            if task.status != "waiting_for_owner": raise HTTPException(409, "Task is not waiting for owner")
            action = owner_action(body.decision, body.action)
            task.status, task.data = "queued", {**task.data, "owner_decision": body.decision, "owner_decision_action": action}
            db.add(Timeline(task_id=task_id, kind="owner_decision", data={"decision": body.decision, "action": action}))
        return {"status": "queued", "action": action}

    @api.get("/plugins")
    def plugins_list():
        return plugin_manager.list()

    @api.get("/plugins/scan")
    def plugins_scan():
        return plugin_manager.scan()

    @api.post("/plugins/install/{filename}", status_code=201)
    def plugin_install(filename: str):
        try:
            return plugin_manager.install(filename)
        except (PluginError, PluginPackageError) as error:
            raise HTTPException(422, str(error)) from error

    @api.post("/plugins/{plugin_id}/enable")
    async def plugin_enable(plugin_id: str):
        try:
            return await plugin_manager.enable(plugin_id)
        except (PluginError, PluginPackageError) as error:
            raise HTTPException(422, str(error)) from error

    @api.post("/plugins/{plugin_id}/disable")
    async def plugin_disable(plugin_id: str):
        try:
            return await plugin_manager.disable(plugin_id)
        except (PluginError, PluginPackageError) as error:
            raise HTTPException(422, str(error)) from error

    @api.delete("/plugins/{plugin_id}", status_code=204)
    async def plugin_uninstall(plugin_id: str):
        try:
            await plugin_manager.uninstall(plugin_id)
        except (PluginError, PluginPackageError) as error:
            raise HTTPException(422, str(error)) from error

    @api.put("/plugins/{plugin_id}/config")
    def plugin_config(plugin_id: str, body: dict[str, object]):
        try:
            return plugin_manager.configure(plugin_id, body)
        except (PluginError, PluginPackageError) as error:
            raise HTTPException(422, str(error)) from error

    @api.post("/plugins/{plugin_id}/secrets/{field_name}/regenerate")
    def plugin_regenerate_secret(plugin_id: str, field_name: str):
        try:
            return {"value": plugin_manager.regenerate_secret(plugin_id, field_name)}
        except (PluginError, PluginPackageError) as error:
            raise HTTPException(422, str(error)) from error

    @api.post("/tasks/{task_id}/retry")
    def retry_task(task_id: str):
        with sessions.begin() as db:
            task = get(db, Task, task_id)
            if not (task.status.startswith("failed_") or task.status == "interrupted"):
                raise HTTPException(409, "Only failed or safely interrupted tasks can be retried")
            unsafe = db.scalar(select(Outbox).where(Outbox.task_id == task_id, Outbox.status.in_(("executing", "unknown"))))
            if unsafe:
                raise HTTPException(409, "Task has an unresolved external action")
            task.status, task.lease_until = "queued", None
            task.data = {key: value for key, value in task.data.items() if key not in {"error", "failure"}}
            db.add(Timeline(task_id=task_id, kind="task_retried", data={"next_attempt": task.attempts + 1}))
        return {"status": "queued"}

    @api.post("/tasks/{task_id}/recheck")
    def recheck_task(task_id: str):
        with sessions.begin() as db:
            task = get(db, Task, task_id)
            allowed = {"bot_skipped", "bot_merge_deferred", "waiting_for_owner", "waiting_for_contributor"}
            if task.kind != "pull_request" or task.status not in allowed:
                raise HTTPException(409, "Only deferred pull request tasks can be rechecked")
            unsafe = db.scalar(select(Outbox).where(Outbox.task_id == task_id, Outbox.status.in_(("executing", "unknown"))))
            if unsafe:
                raise HTTPException(409, "Task has an unresolved external action")
            task.status, task.lease_until = "queued", None
            db.add(Timeline(task_id=task_id, kind="task_rechecked", data={"next_attempt": task.attempts + 1}))
        return {"status": "queued"}

    @api.get("/providers")
    def providers():
        with sessions() as db:
            return [provider_view(p) for p in db.scalars(select(Provider))]

    @api.post("/providers", status_code=201)
    def add_provider(body: ProviderInput):
        with sessions.begin() as db:
            p = Provider(data=body.model_dump(exclude={"api_key"}), encrypted_key=vault.encrypt(body.api_key.get_secret_value()) if body.api_key and body.api_key.get_secret_value() else None)
            db.add(p)
            db.flush()
            return provider_view(p)

    @api.put("/providers/{identifier}")
    def edit_provider(identifier: str, body: ProviderInput):
        with sessions.begin() as db:
            p = get(db, Provider, identifier)
            general = GeneralSettings.model_validate(get(db, Config, "general").data)
            agent_configs = [AgentInput.model_validate(a.data) for a in db.scalars(select(Agent))]
            refs = [general.model] + [a.model for a in agent_configs]
            enabled_models = {item.id for item in body.models if item.enabled}
            if any(r and r.provider == identifier and r.model not in enabled_models for r in refs):
                raise HTTPException(409, "A removed model is still referenced by an agent")
            for agent in [None, *agent_configs]:
                ref = (agent.model if agent else None) or general.model
                if ref and ref.provider == identifier:
                    definition = next(item for item in body.models if item.id == ref.model and item.enabled)
                    validate_agent_layers(definition, general, agent)
            p.data = body.model_dump(exclude={"api_key"})
            if body.api_key and body.api_key.get_secret_value():
                p.encrypted_key = vault.encrypt(body.api_key.get_secret_value())
            return provider_view(p)

    @api.delete("/providers/{identifier}", status_code=204)
    def delete_provider(identifier: str):
        with sessions.begin() as db:
            p = get(db, Provider, identifier)
            refs = [get(db, Config, "general").data.get("model")] + [a.data.get("model") for a in db.scalars(select(Agent))]
            if any(r and r["provider"] == identifier for r in refs):
                raise HTTPException(409, "Provider is still referenced by an agent")
            db.delete(p)

    @api.post("/providers/{identifier}/test")
    async def test_provider(identifier: str):
        with sessions() as db:
            p = get(db, Provider, identifier)
            provider = app.state.provider_factory(p.data["base_url"], vault.decrypt(p.encrypted_key))
        try:
            async with asyncio.timeout(20):
                return {"ok": True, "models": await provider.models()}
        except Exception:
            raise HTTPException(502, "Model listing failed; check endpoint, key and provider compatibility") from None

    @api.post("/providers/{identifier}/models/{model_id}/reset")
    def reset_provider_model(identifier: str, model_id: str, body: ResetInput):
        with sessions.begin() as db:
            row = get(db, Provider, identifier)
            provider = provider_config(row)
            index = next((index for index, model in enumerate(provider.models) if model.id == model_id), None)
            if index is None:
                raise HTTPException(404, "Model not found")
            try:
                provider.models[index] = reset_model(provider.models[index], body.scope)
            except ValueError as error:
                raise HTTPException(422, str(error)) from None
            row.data = provider.model_dump(exclude={"api_key"})
            audit_reset(db, "model", f"{identifier}/{model_id}", body.scope)
            db.flush()
            return {"provider": provider_view(row), "resolved": {name: value.audit_snapshot() for name, value in resolve_all_agents(db).items()}}

    @api.get("/settings")
    def read_settings():
        with sessions() as db:
            return get(db, Config, "general").data

    @api.put("/settings")
    def write_settings(body: GeneralSettings):
        with sessions.begin() as db:
            definition = validate_ref(db, body.model)
            validate_agent_layers(definition, body)
            for row in db.scalars(select(Agent)):
                agent = AgentInput.model_validate(row.data)
                validate_agent_layers(validate_ref(db, agent.model or body.model), body, agent)
            get(db, Config, "general").data = body.model_dump()
        return body

    @api.post("/settings/reset")
    def reset_settings(body: ResetInput):
        with sessions.begin() as db:
            row = get(db, Config, "general")
            try:
                value = reset_main(GeneralSettings.model_validate(row.data), body.scope)
            except ValueError as error:
                raise HTTPException(422, str(error)) from None
            row.data = value.model_dump()
            audit_reset(db, "main_agent", "main", body.scope)
            db.flush()
            resolved = resolve_agent_config(db, "main").audit_snapshot() if value.model else None
            return {"settings": value, "resolved": resolved}

    @api.get("/defaults/prompt")
    def default_prompt():
        return {"system_prompt": DEFAULT_PROMPT}

    @api.get("/agents")
    def agents():
        with sessions() as db:
            # Normalize additive JSON migrations so older rows such as
            # runtime={} always reach the UI with every nested default present.
            return [AgentInput.model_validate(a.data).model_dump() for a in db.scalars(select(Agent))]

    @api.get("/runtime-configs")
    def runtime_configs():
        with sessions() as db:
            return {identifier: config.audit_snapshot() for identifier, config in resolve_all_agents(db).items()}

    @api.post("/agents", status_code=201)
    def add_agent(body: AgentInput):
        with sessions.begin() as db:
            if body.identifier == "main" or db.get(Agent, body.identifier):
                raise HTTPException(409, "Agent identifier already exists or is reserved")
            general = GeneralSettings.model_validate(get(db, Config, "general").data)
            definition = validate_ref(db, body.model or general.model)
            validate_agent_layers(definition, general, body)
            db.add(Agent(id=body.identifier, data=body.model_dump()))
        return body

    @api.put("/agents/{identifier}")
    def edit_agent(identifier: str, body: AgentInput):
        if body.identifier != identifier:
            raise HTTPException(422, "Identifier cannot be changed")
        with sessions.begin() as db:
            general = GeneralSettings.model_validate(get(db, Config, "general").data)
            definition = validate_ref(db, body.model or general.model)
            validate_agent_layers(definition, general, body)
            get(db, Agent, identifier).data = body.model_dump()
        return body

    @api.post("/agents/{identifier}/reset")
    def reset_sub_agent(identifier: str, body: ResetInput):
        with sessions.begin() as db:
            row = get(db, Agent, identifier)
            try:
                value = reset_agent(AgentInput.model_validate(row.data), body.scope)
            except ValueError as error:
                raise HTTPException(422, str(error)) from None
            general = GeneralSettings.model_validate(get(db, Config, "general").data)
            definition = validate_ref(db, value.model or general.model)
            validate_agent_layers(definition, general, value)
            row.data = value.model_dump()
            audit_reset(db, "sub_agent", identifier, body.scope)
            db.flush()
            resolved = resolve_agent_config(db, identifier).audit_snapshot()
            return {"agent": value, "resolved": resolved}

    @api.delete("/agents/{identifier}", status_code=204)
    def delete_agent(identifier: str):
        with sessions.begin() as db:
            db.delete(get(db, Agent, identifier))

    @api.get("/config-audit")
    def config_audit():
        with sessions() as db:
            return [{"id": item.id, "timestamp": item.timestamp, "kind": item.kind, **item.data} for item in db.scalars(select(ConfigAudit).order_by(ConfigAudit.timestamp.desc()).limit(200))]

    @api.get("/sandbox")
    def read_sandbox():
        with sessions() as db:
            data = get(db, Config, "sandbox").data
            return {**{k: v for k, v in data.items() if k != "encrypted_key"}, "has_key": bool(data.get("encrypted_key")), "api_key_masked": "••••••••" if data.get("encrypted_key") else ""}

    @api.put("/sandbox")
    def write_sandbox(body: SandboxSettings):
        with sessions.begin() as db:
            row = get(db, Config, "sandbox")
            encrypted = row.data.get("encrypted_key")
            if body.api_key and body.api_key.get_secret_value():
                encrypted = vault.encrypt(body.api_key.get_secret_value())
            row.data = {**body.model_dump(exclude={"api_key"}), "encrypted_key": encrypted}
        return read_sandbox()

    @api.post("/sandbox/test")
    async def test_sandbox():
        try:
            async with asyncio.timeout(20):
                return await probe_sandbox()
        except Exception:
            raise HTTPException(502, "Sandbox probe failed; verify URL, key and workspace access") from None

    @api.post("/runs", status_code=201)
    async def run_agent(body: RunInput):
        with sessions.begin() as db:
            try:
                resolved = resolve_agent_config(db, body.agent)
            except ValueError as error:
                raise HTTPException(409, str(error)) from None
            p = get(db, Provider, resolved.provider)
            key = vault.decrypt(p.encrypted_key)
            provider = app.state.provider_factory(resolved.base_url, key)
            record = Run(data={"trigger": "manual_diagnostic", "agent": body.agent, "model": resolved.model, "provider": resolved.provider, "repository": None, "number": None, "tool_calls": [], "github_actions": [], "sandbox": None, "runtime_config": resolved.audit_snapshot()})
            db.add(record)
            db.flush()
            run_id = record.id
        try:
            completion = await agent_task(app.state.runtime.run(provider, resolved.model, resolved.system_prompt, body.prompt, resolved.model_timeout, openai_compatible_parameters(resolved)), resolved.task_timeout)
            # A provider might echo its own credential. Never persist that plaintext.
            result = completion.text.replace(key, "[REDACTED]") if key else completion.text
            with sessions.begin() as db:
                record = get(db, Run, run_id)
                record.status, record.ended = "completed", time.time()
                record.data = {**record.data, "result": result[:32000], "usage_reported": completion.usage_reported}
                db.add(Usage(run_id=run_id, data={"provider": resolved.provider, "model": resolved.model, **completion.model_dump(exclude={"text"})}))
                return run_view(record)
        except (Exception, asyncio.CancelledError) as error:
            with sessions.begin() as db:
                record = get(db, Run, run_id)
                record.status, record.ended = "failed", time.time()
                record.data = {**record.data, "error": "Model request failed or timed out; inspect provider configuration"}
                result = run_view(record)
            if isinstance(error, asyncio.CancelledError):
                raise
            return result

    @api.get("/runs")
    def runs():
        with sessions() as db:
            return [run_view(r) for r in db.scalars(select(Run).order_by(Run.started.desc()).limit(100))]

    @api.get("/runs/{identifier}")
    def run_detail(identifier: str):
        with sessions() as db:
            return run_view(get(db, Run, identifier))

    @api.get("/dashboard")
    def dashboard():
        now = time.time()
        with sessions() as db:
            usages = list(db.scalars(select(Usage).where(Usage.timestamp >= now - 30 * 86400)))
            windows = {}
            for days, label in [(1, "24h"), (7, "7d"), (30, "30d")]:
                grouped, totals = {}, {"total": 0, "input": 0, "output": 0, "reasoning": 0, "cached": 0}
                for usage in usages:
                    if usage.timestamp >= now - days * 86400:
                        name = f"{usage.data['provider']} / {usage.data['model']}"
                        value = int(usage.data.get("total_tokens", 0))
                        grouped[name] = grouped.get(name, 0) + value
                        totals["total"] += value
                        totals["input"] += int(usage.data.get("input_tokens", 0))
                        totals["output"] += int(usage.data.get("output_tokens", 0))
                        totals["reasoning"] += int(usage.data.get("reasoning_tokens", 0))
                        totals["cached"] += int(usage.data.get("cached_tokens", 0))
                windows[label] = {**totals, "models": grouped}
            tasks_all = list(db.scalars(select(Task)))
            runs_all = list(db.scalars(select(Run)))
            counts = {
                "running": sum(item.status == "running" for item in tasks_all) + sum(item.status == "running" for item in runs_all),
                "failed": sum(item.status.startswith("failed_") for item in tasks_all) + sum(item.status == "failed" for item in runs_all),
                "owner_pending": sum(item.status == "waiting_for_owner" for item in tasks_all),
                "contributor_pending": sum(item.status == "waiting_for_contributor" for item in tasks_all),
                "interrupted": sum(item.status == "interrupted" for item in tasks_all),
            }
            github = db.get(Config, "github"); sandbox = get(db, Config, "sandbox").data; general = GeneralSettings.model_validate(get(db, Config, "general").data)
            repos = list(db.scalars(select(Repository))); diagnostic = db.get(Config, "setup_diagnostics")
            systems = {
                "database": "healthy",
                "github_app": "ready" if github and github.data.get("private_key") else "unconfigured",
                "webhook": "ready" if github and github.data.get("webhook_secret") else "unconfigured",
                "model": "ready" if general.model else "unconfigured",
                "agent_runtime": "ready" if general.model else "waiting",
                "sandbox": "ready" if sandbox.get("provider") == "local" or sandbox.get("encrypted_key") else "unconfigured",
                "smtp": "ready" if (db.get(Config, "email") and db.get(Config, "email").data.get("enabled")) else "optional",
                "automation": "ready" if any(r.data.get("enabled", True) for r in repos) else "unconfigured",
            }
            automation = {"repositories": len(repos), "issues": sum(r.data.get("auto_handle_issues", False) for r in repos), "reviews": sum(r.data.get("auto_review_prs", False) for r in repos), "auto_merge": sum(r.data.get("auto_merge", False) for r in repos)}
            warnings = sum(value in {"unconfigured", "waiting"} for value in systems.values())
            return {"tokens": windows, "counts": counts, "systems": systems, "automation": automation, "configuration_warnings": warnings, "diagnostics": diagnostic.data if diagnostic else None}

    static = Path(settings.static_dir)
    if (static / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=static / "assets"), name="assets")

    @app.websocket("/api/plugins/{plugin_id}/ws")
    async def plugin_websocket(websocket: WebSocket, plugin_id: str):
        await websocket.accept()
        authenticated = False
        try:
            raw = await asyncio.wait_for(websocket.receive_text(), timeout=10)
            if len(raw.encode("utf-8")) > MAX_MESSAGE_BYTES:
                await websocket.close(code=1009)
                return
            try:
                first = json.loads(raw)
            except Exception:
                await websocket.close(code=1003)
                return
            if not await plugin_manager.authenticate_transport(plugin_id, first):
                await websocket.close(code=1008)
                return
            authenticated = True
            await plugin_manager.connect(plugin_id, websocket, first)
            while True:
                raw = await websocket.receive_text()
                if len(raw.encode("utf-8")) > MAX_MESSAGE_BYTES:
                    await websocket.close(code=1009)
                    return
                try:
                    message = json.loads(raw)
                except Exception:
                    await websocket.send_json({"protocol": "maintune.astrbot.v1", "type": "error", "code": "MALFORMED_MESSAGE"})
                    continue
                for response in await plugin_manager.transport_message(plugin_id, message):
                    await websocket.send_json(response)
        except (WebSocketDisconnect, TimeoutError):
            pass
        except PluginError:
            if authenticated:
                await websocket.close(code=1011)
        finally:
            await plugin_manager.disconnect(plugin_id, websocket)

    # FastAPI 0.141 represents include_router as one catch-all ASGI route.
    # Static mounts must be registered first or the authenticated API router
    # intercepts /assets/* and returns 401 before the browser can start React.
    app.include_router(api)

    @app.get("/")
    def index():
        if not (static / "index.html").is_file():
            return JSONResponse({"detail": "Build the frontend first; see README"}, status_code=503)
        return FileResponse(static / "index.html")

    return app
