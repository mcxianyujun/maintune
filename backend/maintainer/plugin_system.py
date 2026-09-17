from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import sys
import tempfile
import time
import uuid
import venv
import zipfile
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select

from .db import Config, Repository, Task, Timeline
from .policy import owner_action


PLUGIN_API_VERSION = 1
PLUGIN_PROTOCOL = "maintune.plugin.v1"
MAX_ARCHIVE_BYTES = 20 * 1024 * 1024
MAX_UNPACKED_BYTES = 50 * 1024 * 1024
MAX_ARCHIVE_FILES = 512
MAX_MESSAGE_BYTES = 1024 * 1024
PLUGIN_ID = re.compile(r"^[a-z0-9][a-z0-9.-]{2,127}$")
SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")


class PluginError(RuntimeError):
    pass


class PluginPackageError(PluginError):
    pass


class PluginCapabilityError(PluginError):
    pass


class PluginConfigField(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["string", "boolean", "integer", "select", "string_list", "secret"]
    title: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    required: bool = False
    default: Any = None
    options: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_shape(self):
        if self.type == "select" and not self.options:
            raise ValueError("select fields require options")
        if self.type == "secret" and self.default not in (None, ""):
            raise ValueError("secret defaults are forbidden")
        return self


class PluginEntrypoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    python: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_.]{0,199}$")


class MaintuneCompatibility(BaseModel):
    model_config = ConfigDict(extra="forbid")
    min_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")


class PluginManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str = Field(min_length=1, max_length=100)
    version: str
    api_version: int = Field(ge=1, le=1000)
    publisher: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    maintune: MaintuneCompatibility
    capabilities: list[Literal["repository.read", "task.read", "event.subscribe", "owner_decision.submit", "plugin.log", "plugin.health"]] = Field(default_factory=list, max_length=32)
    entrypoint: PluginEntrypoint
    config: dict[str, PluginConfigField] = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def valid_id(cls, value: str) -> str:
        if not PLUGIN_ID.fullmatch(value):
            raise ValueError("invalid plugin id")
        return value

    @field_validator("version")
    @classmethod
    def valid_version(cls, value: str) -> str:
        if not SEMVER.fullmatch(value):
            raise ValueError("invalid plugin version")
        return value

    @field_validator("capabilities")
    @classmethod
    def unique_capabilities(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("duplicate capability")
        return value


class PluginEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    protocol: Literal["maintune.plugin.v1"] = PLUGIN_PROTOCOL
    event: str = Field(pattern=r"^[a-z][a-z0-9_.]{1,79}$")
    event_id: str = Field(pattern=r"^evt_[a-f0-9]{32}$")
    timestamp: str
    repository: str | None = None
    task: dict[str, Any] | None = None
    data: dict[str, Any] = Field(default_factory=dict)


def _scalar(value: str) -> Any:
    value = value.strip()
    if not value:
        return None
    if value in {"true", "True"}:
        return True
    if value in {"false", "False"}:
        return False
    if value in {"null", "Null", "~"}:
        return None
    if value.startswith(("[", "{", '"')):
        try:
            return json.loads(value)
        except json.JSONDecodeError as error:
            raise PluginPackageError("Invalid JSON-compatible YAML scalar") from error
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'")
    if re.fullmatch(r"-?[0-9]+", value):
        return int(value)
    return value


def parse_manifest_yaml(text: str) -> dict[str, Any]:
    """Parse the deliberately small, safe YAML subset used by .mtp manifests."""
    if text.lstrip().startswith("{"):
        try:
            value = json.loads(text)
        except json.JSONDecodeError as error:
            raise PluginPackageError("Invalid manifest") from error
        if not isinstance(value, dict):
            raise PluginPackageError("Manifest root must be a mapping")
        return value

    tokens: list[tuple[int, str]] = []
    for number, raw in enumerate(text.splitlines(), 1):
        if "\t" in raw:
            raise PluginPackageError(f"Tabs are not allowed in manifest line {number}")
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        if indent % 2:
            raise PluginPackageError(f"Manifest indentation must use two spaces at line {number}")
        tokens.append((indent, stripped))

    def block(index: int, indent: int) -> tuple[Any, int]:
        is_list = tokens[index][1].startswith("- ")
        result: Any = [] if is_list else {}
        while index < len(tokens):
            current_indent, line = tokens[index]
            if current_indent < indent:
                break
            if current_indent != indent or line.startswith("- ") != is_list:
                raise PluginPackageError("Invalid manifest indentation or mixed collection")
            if is_list:
                result.append(_scalar(line[2:]))
                index += 1
                continue
            if ":" not in line:
                raise PluginPackageError("Manifest mapping entry is missing ':'")
            key, raw_value = line.split(":", 1)
            key = key.strip()
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]{0,99}", key) or key in result:
                raise PluginPackageError("Invalid or duplicate manifest key")
            index += 1
            if raw_value.strip():
                result[key] = _scalar(raw_value)
            elif index < len(tokens) and tokens[index][0] > indent:
                result[key], index = block(index, tokens[index][0])
            else:
                result[key] = {}
        return result, index

    if not tokens:
        raise PluginPackageError("Manifest is empty")
    value, end = block(0, tokens[0][0])
    if end != len(tokens) or not isinstance(value, dict):
        raise PluginPackageError("Manifest root must be a mapping")
    return value


def load_manifest(path: Path) -> PluginManifest:
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise PluginPackageError("Manifest cannot be read as UTF-8") from error
    if len(raw.encode("utf-8")) > 256 * 1024:
        raise PluginPackageError("Manifest is too large")
    try:
        return PluginManifest.model_validate(parse_manifest_yaml(raw))
    except Exception as error:
        if isinstance(error, PluginPackageError):
            raise
        raise PluginPackageError("Manifest schema validation failed") from error


def _safe_member(info: zipfile.ZipInfo) -> PurePosixPath:
    if "\\" in info.filename or "\x00" in info.filename:
        raise PluginPackageError("Archive contains an unsafe path")
    path = PurePosixPath(info.filename)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise PluginPackageError("Archive contains an unsafe path")
    mode = info.external_attr >> 16
    if stat.S_ISLNK(mode):
        raise PluginPackageError("Archive symlinks are forbidden")
    return path


class PluginPackageManager:
    def __init__(self, root: Path, maintune_version: str):
        self.root = root.resolve()
        self.maintune_version = maintune_version
        self.inbox = self.root / "inbox"
        self.installed = self.root / "installed"
        self.runtime = self.root / "runtime"
        for directory in (self.inbox, self.installed, self.runtime):
            directory.mkdir(parents=True, exist_ok=True)

    def validate(self, archive: Path) -> PluginManifest:
        if archive.suffix.lower() != ".mtp" or not archive.is_file():
            raise PluginPackageError("Plugin package must be a .mtp file")
        if archive.stat().st_size > MAX_ARCHIVE_BYTES:
            raise PluginPackageError("Plugin package is too large")
        try:
            with zipfile.ZipFile(archive) as package:
                infos = package.infolist()
                if len(infos) > MAX_ARCHIVE_FILES:
                    raise PluginPackageError("Plugin package has too many files")
                total = 0
                seen: set[str] = set()
                for info in infos:
                    path = _safe_member(info)
                    normalized = path.as_posix()
                    if normalized in seen:
                        raise PluginPackageError("Plugin package contains duplicate paths")
                    seen.add(normalized)
                    total += info.file_size
                    if total > MAX_UNPACKED_BYTES:
                        raise PluginPackageError("Plugin package expands beyond the size limit")
                if "manifest.yaml" not in seen:
                    raise PluginPackageError("Plugin package is missing manifest.yaml")
                if "requirements.lock" not in seen:
                    raise PluginPackageError("Plugin package is missing requirements.lock")
                if not any(name.startswith("src/") and not name.endswith("/") for name in seen):
                    raise PluginPackageError("Plugin package is missing source files")
                manifest_bytes = package.read("manifest.yaml")
        except (zipfile.BadZipFile, OSError) as error:
            raise PluginPackageError("Invalid plugin package") from error
        if len(manifest_bytes) > 256 * 1024:
            raise PluginPackageError("Manifest is too large")
        try:
            manifest_data = parse_manifest_yaml(manifest_bytes.decode("utf-8"))
            manifest = PluginManifest.model_validate(manifest_data)
        except Exception as error:
            if isinstance(error, PluginPackageError):
                raise
            raise PluginPackageError("Manifest schema validation failed") from error
        if manifest.api_version != PLUGIN_API_VERSION:
            raise PluginPackageError("Unsupported Plugin API version")
        if self._version_tuple(manifest.maintune.min_version) > self._version_tuple(self.maintune_version):
            raise PluginPackageError("Plugin requires a newer Maintune version")
        module_path = "src/" + manifest.entrypoint.python.replace(".", "/") + ".py"
        package_path = "src/" + manifest.entrypoint.python.replace(".", "/") + "/__main__.py"
        if module_path not in seen and package_path not in seen:
            raise PluginPackageError("Plugin entrypoint is missing")
        return manifest

    @staticmethod
    def _version_tuple(value: str) -> tuple[int, int, int]:
        match = re.match(r"^(\d+)\.(\d+)\.(\d+)", value)
        return tuple(map(int, match.groups())) if match else (0, 0, 0)

    def install(self, archive: Path) -> PluginManifest:
        manifest = self.validate(archive)
        destination = self.installed / manifest.id
        if destination.exists():
            raise PluginPackageError("Plugin id is already installed")
        staging = Path(tempfile.mkdtemp(prefix="install-", dir=self.runtime))
        try:
            with zipfile.ZipFile(archive) as package:
                for info in package.infolist():
                    relative = _safe_member(info)
                    target = (staging / Path(*relative.parts)).resolve()
                    if staging.resolve() not in target.parents and target != staging.resolve():
                        raise PluginPackageError("Plugin path escapes staging directory")
                    if info.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with package.open(info) as source, target.open("wb") as output:
                            shutil.copyfileobj(source, output)
            os.replace(staging, destination)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        return manifest

    def uninstall(self, plugin_id: str) -> None:
        if not PLUGIN_ID.fullmatch(plugin_id):
            raise PluginPackageError("Invalid plugin id")
        destination = (self.installed / plugin_id).resolve()
        if destination.parent != self.installed:
            raise PluginPackageError("Invalid plugin path")
        shutil.rmtree(destination, ignore_errors=False)
        runtime = (self.runtime / plugin_id).resolve()
        if runtime.parent == self.runtime and runtime.exists():
            shutil.rmtree(runtime, ignore_errors=False)

    def discover(self) -> list[PluginManifest]:
        manifests = []
        for path in sorted(self.installed.iterdir() if self.installed.exists() else []):
            if path.is_dir() and (path / "manifest.yaml").is_file():
                try:
                    manifests.append(load_manifest(path / "manifest.yaml"))
                except PluginPackageError:
                    continue
        return manifests


CapabilityHandler = Callable[[str, dict[str, Any]], Awaitable[Any]]


class PluginProcess:
    def __init__(self, manifest: PluginManifest, plugin_dir: Path, runtime_dir: Path, capability_handler: CapabilityHandler):
        self.manifest = manifest
        self.plugin_dir = plugin_dir
        self.runtime_dir = runtime_dir
        self.capability_handler = capability_handler
        self.process: asyncio.subprocess.Process | None = None
        self.pending: dict[str, asyncio.Future] = {}
        self.reader_task: asyncio.Task | None = None
        self.stderr_task: asyncio.Task | None = None
        self.stderr_tail = ""
        self.write_lock = asyncio.Lock()
        self.started_at: float | None = None

    def _python(self) -> Path:
        return self.runtime_dir / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

    async def start(self, timeout: float = 10) -> None:
        if self.process and self.process.returncode is None:
            return
        python = self._python()
        if not python.exists():
            self.runtime_dir.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(venv.EnvBuilder(with_pip=True, clear=False).create, self.runtime_dir / "venv")
        await self._install_locked_requirements(python)
        bootstrap = "import runpy,sys;sys.path.insert(0,sys.argv[1]);runpy.run_module(sys.argv[2],run_name='__main__')"
        child_env = {
            key: value
            for key, value in os.environ.items()
            if key.upper() in {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP", "LANG", "LC_ALL"}
        }
        child_env.update({"PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"})
        self.process = await asyncio.create_subprocess_exec(
            str(python), "-I", "-c", bootstrap, str(self.plugin_dir / "src"), self.manifest.entrypoint.python,
            cwd=self.plugin_dir,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=child_env,
        )
        self.reader_task = asyncio.create_task(self._reader())
        self.stderr_task = asyncio.create_task(self._stderr())
        self.started_at = time.time()
        try:
            await asyncio.wait_for(self.request("lifecycle.start", {"api_version": 1}), timeout)
        except Exception:
            detail = re.sub(r"(?i)(token|password|secret|authorization)\s*[:=]\s*\S+", r"\1=[REDACTED]", self.stderr_tail).strip()
            await self.stop()
            raise PluginError("Plugin failed to start" + (f": {detail[-500:]}" if detail else ""))

    async def _install_locked_requirements(self, python: Path) -> None:
        requirements = self.plugin_dir / "requirements.lock"
        content = requirements.read_text(encoding="utf-8")
        effective = [line.strip() for line in content.splitlines() if line.strip() and not line.lstrip().startswith("#")]
        digest = hashlib.sha256(content.encode()).hexdigest()
        marker = self.runtime_dir / "requirements.sha256"
        if marker.is_file() and marker.read_text(encoding="ascii").strip() == digest:
            return
        for line in effective:
            lowered = line.lower()
            if any(value in lowered for value in ("git+", "file:", "-e ", "--editable", "--index-url", "--extra-index-url")):
                raise PluginError("Plugin dependency lock contains a forbidden source")
            if "==" not in line or "--hash=sha256:" not in line:
                raise PluginError("Plugin dependencies must be pinned with SHA-256 hashes")
        if effective:
            process = await asyncio.create_subprocess_exec(
                str(python), "-I", "-m", "pip", "--disable-pip-version-check", "install", "--require-hashes", "--no-deps", "--requirement", str(requirements),
                cwd=self.plugin_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            try:
                output, _ = await asyncio.wait_for(process.communicate(), 300)
            except TimeoutError:
                process.kill()
                await process.wait()
                raise PluginError("Plugin dependency installation timed out")
            if process.returncode:
                message = output.decode("utf-8", "replace")
                message = re.sub(r"https?://\S+", "[REDACTED URL]", message)
                raise PluginError("Plugin dependency installation failed: " + message[-500:])
        marker.write_text(digest, encoding="ascii")

    async def stop(self) -> None:
        process = self.process
        if not process:
            return
        if process.returncode is None:
            try:
                await asyncio.wait_for(self.request("lifecycle.stop", {}), 2)
            except Exception:
                pass
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), 3)
                except TimeoutError:
                    process.kill()
                    await process.wait()
        current = asyncio.current_task()
        for task in (self.reader_task, self.stderr_task):
            if task and task is not current and not task.done():
                task.cancel()
        self.process = None

    async def request(self, method: str, params: dict[str, Any], timeout: float = 10) -> Any:
        if not self.process or self.process.returncode is not None or not self.process.stdin:
            raise PluginError("Plugin is not running")
        identifier = uuid.uuid4().hex
        future = asyncio.get_running_loop().create_future()
        self.pending[identifier] = future
        await self._write({"jsonrpc": "2.0", "id": identifier, "method": method, "params": params})
        try:
            return await asyncio.wait_for(future, timeout)
        finally:
            self.pending.pop(identifier, None)

    async def notify(self, method: str, params: dict[str, Any]) -> None:
        if self.process and self.process.returncode is None:
            await self._write({"jsonrpc": "2.0", "method": method, "params": params})

    async def _write(self, message: dict[str, Any]) -> None:
        encoded = (json.dumps(message, separators=(",", ":"), ensure_ascii=False) + "\n").encode()
        if len(encoded) > MAX_MESSAGE_BYTES:
            raise PluginError("Plugin message exceeds size limit")
        async with self.write_lock:
            if not self.process or not self.process.stdin:
                raise PluginError("Plugin is not running")
            self.process.stdin.write(encoded)
            await self.process.stdin.drain()

    async def _reader(self) -> None:
        assert self.process and self.process.stdout
        try:
            while line := await self.process.stdout.readline():
                if len(line) > MAX_MESSAGE_BYTES:
                    raise PluginError("Plugin message exceeds size limit")
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if "method" in message and "id" in message:
                    asyncio.create_task(self._handle_call(message))
                elif "id" in message:
                    future = self.pending.get(str(message["id"]))
                    if future and not future.done():
                        if "error" in message:
                            future.set_exception(PluginError(str(message["error"].get("message", "Plugin error"))))
                        else:
                            future.set_result(message.get("result"))
        finally:
            error = PluginError("Plugin process exited")
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(error)

    async def _handle_call(self, message: dict[str, Any]) -> None:
        identifier = str(message["id"])
        try:
            if message.get("method") != "capability.call":
                raise PluginCapabilityError("Unsupported plugin call")
            params = message.get("params") or {}
            result = await self.capability_handler(str(params.get("capability", "")), params)
            await self._write({"jsonrpc": "2.0", "id": identifier, "result": result})
        except Exception as error:
            await self._write({"jsonrpc": "2.0", "id": identifier, "error": {"code": "CAPABILITY_DENIED", "message": str(error)[:500]}})

    async def _stderr(self) -> None:
        assert self.process and self.process.stderr
        while chunk := await self.process.stderr.read(1024):
            text = chunk.decode("utf-8", "replace")
            text = re.sub(r"(?i)(token|password|secret|authorization)\s*[:=]\s*\S+", r"\1=[REDACTED]", text)
            self.stderr_tail = (self.stderr_tail + text)[-4096:]

    def state(self) -> str:
        if not self.process:
            return "stopped"
        return "running" if self.process.returncode is None else "error"


class PluginCapabilityBroker:
    def __init__(self, sessions, plugin_id: str, capabilities: set[str]):
        self.sessions = sessions
        self.plugin_id = plugin_id
        self.capabilities = capabilities

    async def call(self, capability: str, params: dict[str, Any]) -> Any:
        if capability not in self.capabilities:
            raise PluginCapabilityError(f"Capability {capability!r} was not granted")
        action = str(params.get("action", ""))
        if capability == "repository.read":
            return self._repository_read(action, params)
        if capability == "task.read":
            return self._task_read(action, params)
        if capability == "owner_decision.submit":
            return self._owner_decision(action, params)
        if capability == "event.subscribe":
            return {"accepted": True, "events": list(params.get("events") or [])[:100]}
        if capability in {"plugin.log", "plugin.health"}:
            return {"accepted": True}
        raise PluginCapabilityError("Capability is not implemented")

    @staticmethod
    def _repository_view(repository: Repository) -> dict[str, Any]:
        data = repository.data if isinstance(repository.data, dict) else {}
        return {
            "full_name": repository.full_name,
            "enabled": bool(data.get("enabled", True)),
            "default_branch": str(data.get("default_branch") or ""),
        }

    def _repository_read(self, action: str, params: dict[str, Any]) -> Any:
        with self.sessions() as db:
            if action == "list":
                limit = min(max(int(params.get("limit", 20)), 1), 100)
                rows = db.scalars(select(Repository).order_by(Repository.full_name).limit(limit))
                return [self._repository_view(row) for row in rows]
            if action == "get":
                full_name = str(params.get("full_name", ""))
                row = db.get(Repository, full_name)
                if not row:
                    raise PluginCapabilityError("Repository not found")
                return self._repository_view(row)
        raise PluginCapabilityError("Unsupported repository.read action")

    def _task_view(self, task: Task) -> dict[str, Any]:
        return {"id": task.id, "kind": task.kind, "repository": task.repository, "number": task.number, "status": task.status, "created": task.created, "updated": task.updated, "title": task.data.get("title") or task.data.get("summary") or ""}

    def _task_read(self, action: str, params: dict[str, Any]) -> Any:
        with self.sessions() as db:
            if action == "status":
                rows = list(db.scalars(select(Task)))
                return {"status": "ok", "counts": {"running": sum(row.status == "running" for row in rows), "waiting_for_owner": sum(row.status == "waiting_for_owner" for row in rows), "failed": sum(row.status.startswith("failed_") for row in rows)}}
            if action == "list":
                limit = min(max(int(params.get("limit", 20)), 1), 100)
                return [self._task_view(row) for row in db.scalars(select(Task).order_by(Task.created.desc()).limit(limit))]
            if action == "get":
                row = db.get(Task, str(params.get("task_id", "")))
                if not row:
                    raise PluginCapabilityError("Task not found")
                timeline = list(db.scalars(select(Timeline).where(Timeline.task_id == row.id).order_by(Timeline.timestamp)))
                return {**self._task_view(row), "summary": row.data.get("summary", ""), "timeline": [{"timestamp": item.timestamp, "kind": item.kind, "data": item.data} for item in timeline[-50:]]}
        raise PluginCapabilityError("Unsupported task.read action")

    def _owner_decision(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        if action != "submit":
            raise PluginCapabilityError("Unsupported owner_decision.submit action")
        task_id = str(params.get("task_id", ""))
        decision_action = str(params.get("decision", ""))
        replay_key = str(params.get("replay_key", ""))
        if decision_action not in {"implement", "reject", "defer"} or not re.fullmatch(r"[A-Za-z0-9_.:-]{8,200}", replay_key):
            raise PluginCapabilityError("Invalid owner decision")
        replay_id = f"plugin-replay:{self.plugin_id}:{hashlib.sha256(replay_key.encode()).hexdigest()}"
        with self.sessions.begin() as db:
            if db.get(Config, replay_id):
                raise PluginCapabilityError("Owner decision replay rejected")
            task = db.get(Task, task_id)
            if not task:
                raise PluginCapabilityError("Task not found")
            if task.status != "waiting_for_owner":
                raise PluginCapabilityError("Task is not waiting for owner")
            normalized = owner_action(decision_action, decision_action)
            task.status = "queued"
            task.data = {**task.data, "owner_decision": f"Plugin decision: {normalized}", "owner_decision_action": normalized, "owner_decision_source": self.plugin_id}
            db.add(Timeline(task_id=task_id, kind="owner_decision", data={"action": normalized, "source": self.plugin_id}))
            db.add(Config(id=replay_id, data={"created": time.time(), "task_id": task_id, "action": normalized}))
        return {"status": "queued", "action": normalized}


def make_event(event: str, task: Task | None = None, data: dict[str, Any] | None = None) -> PluginEvent:
    safe_data = dict(data or {})
    for key in list(safe_data):
        if any(word in key.lower() for word in ("secret", "token", "password", "prompt", "private_key", "credential")):
            safe_data.pop(key)
    return PluginEvent(
        event=event,
        event_id="evt_" + uuid.uuid4().hex,
        timestamp=datetime.now(UTC).isoformat(),
        repository=task.repository if task else None,
        task={"id": task.id, "kind": task.kind, "number": task.number, "status": task.status, "title": task.data.get("title") or task.data.get("summary") or ""} if task else None,
        data=safe_data,
    )


def generate_bridge_token() -> str:
    return secrets.token_urlsafe(48)
