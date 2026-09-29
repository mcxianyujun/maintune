from __future__ import annotations

import asyncio
import hashlib
import importlib.util
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

from packaging.version import InvalidVersion, Version
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select

from .db import Config, Repository, Task, Timeline
from .policy import owner_action


PLUGIN_API_VERSION = 2
LEGACY_PLUGIN_API_VERSION = 1
PLUGIN_PROTOCOL = "maintune.plugin.v1"
PLUGIN_PROTOCOL_V2 = "maintune.plugin.v2"
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
    max_version: str | None = Field(default=None, pattern=r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")


class PluginRuntimeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    default: Literal["isolated", "in_process"] = "isolated"
    supported: list[Literal["isolated", "in_process"]] = Field(default_factory=lambda: ["isolated"], min_length=1, max_length=2)

    @model_validator(mode="after")
    def validate_modes(self):
        if len(set(self.supported)) != len(self.supported) or self.default not in self.supported:
            raise ValueError("runtime default must be included in unique supported modes")
        return self


class PluginPythonSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dependencies: str | None = Field(default=None, max_length=200)

    @field_validator("dependencies")
    @classmethod
    def valid_dependency_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        path = PurePosixPath(value)
        if path.is_absolute() or "\\" in value or any(part in {"", ".", ".."} for part in path.parts):
            raise ValueError("Python dependency path must stay inside the plugin package")
        return value


class PluginDependency(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9.-]{2,127}$")
    version: str = Field(default="*", max_length=80)
    requirement: Literal["required", "optional"] = "required"


class PluginUISpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["bundled", "iframe"]
    entrypoint: str = Field(min_length=1, max_length=200)

    @field_validator("entrypoint")
    @classmethod
    def valid_ui_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or "\\" in value or any(part in {"", ".", ".."} for part in path.parts):
            raise ValueError("UI entrypoint must stay inside the plugin package")
        return value


class PluginManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str = Field(min_length=1, max_length=100)
    version: str
    plugin_api: int = Field(ge=1, le=2)
    api_version: int | None = Field(default=None, ge=1, le=1)
    publisher: str = Field(min_length=1, max_length=100)
    license: str = Field(default="", max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9 .+()/-]{0,99}$")
    description: str = Field(default="", max_length=500)
    maintune: MaintuneCompatibility
    capabilities: list[Literal["repository.read", "task.read", "event.subscribe", "owner_decision.submit", "plugin.log", "plugin.health"]] = Field(default_factory=list, max_length=32)
    entrypoint: PluginEntrypoint
    config: dict[str, PluginConfigField] = Field(default_factory=dict)
    runtime: PluginRuntimeSpec = Field(default_factory=PluginRuntimeSpec)
    python: PluginPythonSpec = Field(default_factory=PluginPythonSpec)
    dependencies: list[PluginDependency] = Field(default_factory=list, max_length=64)
    config_schema: dict[str, Any] | None = None
    ui: PluginUISpec | None = None

    @model_validator(mode="before")
    @classmethod
    def accept_legacy_api_version(cls, value):
        if isinstance(value, dict):
            value = dict(value)
            if "plugin_api" not in value:
                value["plugin_api"] = value.get("api_version", LEGACY_PLUGIN_API_VERSION)
        return value

    @model_validator(mode="after")
    def validate_api_shape(self):
        if self.api_version is not None and self.api_version != self.plugin_api:
            raise ValueError("api_version and plugin_api disagree")
        if self.plugin_api == 1:
            if self.api_version not in (None, 1):
                raise ValueError("Legacy API version must be 1")
        elif self.capabilities:
            raise ValueError("Plugin API v2 registers extensions at runtime; manifest capabilities are not supported")
        if len({item.id for item in self.dependencies}) != len(self.dependencies):
            raise ValueError("duplicate Maintune plugin dependency")
        if self.config_schema is not None:
            from .plugin_api_v2 import validate_config_schema
            validate_config_schema(self.config_schema)
        return self

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

    @property
    def is_legacy(self) -> bool:
        return self.plugin_api == LEGACY_PLUGIN_API_VERSION


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
    reserved = {"con", "prn", "aux", "nul", *(f"com{index}" for index in range(1, 10)), *(f"lpt{index}" for index in range(1, 10))}
    for part in path.parts:
        if ":" in part or part.endswith((" ", ".")) or part.split(".", 1)[0].casefold() in reserved:
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
                seen_folded: set[str] = set()
                for info in infos:
                    path = _safe_member(info)
                    normalized = path.as_posix()
                    if normalized in seen or normalized.casefold() in seen_folded:
                        raise PluginPackageError("Plugin package contains duplicate paths")
                    seen.add(normalized)
                    seen_folded.add(normalized.casefold())
                    total += info.file_size
                    if total > MAX_UNPACKED_BYTES:
                        raise PluginPackageError("Plugin package expands beyond the size limit")
                if "manifest.yaml" not in seen:
                    raise PluginPackageError("Plugin package is missing manifest.yaml")
                if not any(name.startswith("src/") and not name.endswith("/") for name in seen):
                    raise PluginPackageError("Plugin package is missing source files")
                manifest_bytes = package.read("manifest.yaml")
        except (zipfile.BadZipFile, OSError) as error:
            raise PluginPackageError("Invalid plugin package") from error
        if len(manifest_bytes) > 256 * 1024:
            raise PluginPackageError("Manifest is too large")
        try:
            manifest_data = parse_manifest_yaml(manifest_bytes.decode("utf-8"))
            if manifest_data.get("api_version") not in (None, LEGACY_PLUGIN_API_VERSION):
                raise PluginPackageError("Unsupported Plugin API version")
            if manifest_data.get("plugin_api", LEGACY_PLUGIN_API_VERSION) not in (LEGACY_PLUGIN_API_VERSION, PLUGIN_API_VERSION):
                raise PluginPackageError("Unsupported Plugin API version")
            manifest = PluginManifest.model_validate(manifest_data)
        except Exception as error:
            if isinstance(error, PluginPackageError):
                raise
            raise PluginPackageError("Manifest schema validation failed") from error
        if manifest.plugin_api not in (LEGACY_PLUGIN_API_VERSION, PLUGIN_API_VERSION):
            raise PluginPackageError("Unsupported Plugin API version")
        if manifest.is_legacy and "requirements.lock" not in seen:
            raise PluginPackageError("Plugin API v1 package is missing requirements.lock")
        dependencies = manifest.python.dependencies
        if dependencies and dependencies not in seen:
            raise PluginPackageError("Plugin Python dependency file is missing")
        if manifest.ui and manifest.ui.entrypoint not in seen:
            raise PluginPackageError("Plugin UI entrypoint is missing")
        if any(PurePosixPath(name).name.casefold() in {"install.py", "setup.sh", "post_install.py"} for name in seen):
            raise PluginPackageError("Custom plugin installation scripts are not supported")
        # A bare floor such as 0.1.0 historically admitted Preview builds of
        # that release. Keep that contract while comparing explicit Preview
        # numbers accurately (preview.4 must not run on preview.3).
        minimum = manifest.maintune.min_version
        if re.fullmatch(r"\d+\.\d+\.\d+", minimum):
            minimum += ".dev0"
        if self._version_tuple(minimum) > self._version_tuple(self.maintune_version):
            raise PluginPackageError("Plugin requires a newer Maintune version")
        if manifest.maintune.max_version and self._version_tuple(manifest.maintune.max_version) < self._version_tuple(self.maintune_version):
            raise PluginPackageError("Plugin does not support this Maintune version")
        module_path = "src/" + manifest.entrypoint.python.replace(".", "/") + ".py"
        package_init = "src/" + manifest.entrypoint.python.replace(".", "/") + "/__init__.py"
        package_main = "src/" + manifest.entrypoint.python.replace(".", "/") + "/__main__.py"
        if module_path not in seen and package_init not in seen and package_main not in seen:
            raise PluginPackageError("Plugin entrypoint is missing")
        return manifest

    @staticmethod
    def _version_tuple(value: str) -> Version:
        try:
            return Version(value)
        except InvalidVersion as error:
            raise PluginPackageError("Invalid Maintune compatibility version") from error

    def install(self, archive: Path, *, replace: bool = False) -> PluginManifest:
        manifest = self.validate(archive)
        destination = self.installed / manifest.id
        if destination.exists() and not replace:
            raise PluginPackageError("Plugin id is already installed")
        if replace and not destination.is_dir():
            raise PluginPackageError("Plugin is not installed")
        staging = Path(tempfile.mkdtemp(prefix="install-", dir=self.runtime))
        previous: Path | None = None
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
            if replace:
                previous = self.runtime / f"upgrade-old-{uuid.uuid4().hex}"
                os.replace(destination, previous)
            try:
                os.replace(staging, destination)
            except Exception:
                if previous and previous.is_dir():
                    os.replace(previous, destination)
                    previous = None
                raise
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        finally:
            if previous and previous.is_dir() and destination.is_dir() and previous.parent.resolve() == self.runtime.resolve():
                shutil.rmtree(previous)
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
        self.registrations: list[dict[str, Any]] = []
        self._secret_values: tuple[str, ...] = ()

    def _python(self) -> Path:
        return self.runtime_dir / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

    async def start(self, timeout: float = 10, context: dict[str, Any] | None = None) -> None:
        if self.process and self.process.returncode is None:
            return
        python = self._python()
        if not python.exists():
            self.runtime_dir.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(venv.EnvBuilder(with_pip=True, clear=False).create, self.runtime_dir / "venv")
        await self._install_locked_requirements(python)
        if self.manifest.is_legacy:
            bootstrap = "import runpy,sys;sys.path.insert(0,sys.argv[1]);runpy.run_module(sys.argv[2],run_name='__main__')"
            arguments = (str(self.plugin_dir / "src"), self.manifest.entrypoint.python)
            start_params: dict[str, Any] = {"api_version": 1}
        else:
            sdk_root = self.runtime_dir / "sdk"
            await asyncio.to_thread(self._stage_sdk, sdk_root)
            bootstrap = "import sys;sys.path.insert(0,sys.argv[1]);sys.path.insert(0,sys.argv[2]);from maintune_plugin_sdk.runner import run_stdio;run_stdio()"
            arguments = (str(sdk_root), str(self.plugin_dir / "src"))
            start_context = context or {}
            self._secret_values = tuple(str(value) for name, value in (start_context.get("config") or {}).items() if name in start_context.get("secret_fields", ()) and value)
            start_params = {
                "protocol": PLUGIN_PROTOCOL_V2,
                "plugin_src": str(self.plugin_dir / "src"),
                "entrypoint": self.manifest.entrypoint.python,
                "context": start_context,
            }
        child_env = {
            key: value
            for key, value in os.environ.items()
            if key.upper() in {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP", "LANG", "LC_ALL"}
        }
        child_env.update({"PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"})
        self.process = await asyncio.create_subprocess_exec(
            str(python), "-I", "-u", "-c", bootstrap, *arguments,
            cwd=self.plugin_dir,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=child_env,
            limit=MAX_MESSAGE_BYTES,
        )
        self.reader_task = asyncio.create_task(self._reader())
        self.stderr_task = asyncio.create_task(self._stderr())
        self.started_at = time.time()
        try:
            result = await asyncio.wait_for(self.request("lifecycle.start", start_params), timeout)
            if not self.manifest.is_legacy:
                if not isinstance(result, dict) or result.get("protocol") != PLUGIN_PROTOCOL_V2 or not isinstance(result.get("registrations"), list):
                    raise PluginError("Plugin API v2 registration response is invalid")
                self.registrations = result["registrations"]
        except Exception:
            detail = self._sanitize(self.stderr_tail).strip()
            await self.stop()
            raise PluginError("Plugin failed to start" + (f": {detail[-500:]}" if detail else ""))

    @staticmethod
    def _stage_sdk(destination: Path) -> None:
        try:
            import maintune_plugin_sdk
            source = Path(maintune_plugin_sdk.__file__).resolve().parent
        except ModuleNotFoundError:
            # Editable development environments created before the SDK was
            # added may not expose it until the next editable install.
            source = Path(__file__).resolve().parents[2] / "sdk" / "maintune_plugin_sdk"
            if not (source / "runner.py").is_file():
                raise PluginError("Maintune Plugin SDK is not installed")
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, destination / "maintune_plugin_sdk", dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

    def _sanitize(self, message: str) -> str:
        message = re.sub(r"(?i)(token|password|secret|authorization)\s*[:=]\s*\S+", r"\1=[REDACTED]", message)
        for secret in self._secret_values:
            message = message.replace(secret, "[REDACTED]")
        return message

    async def _install_locked_requirements(self, python: Path) -> None:
        dependency_file = "requirements.lock" if self.manifest.is_legacy else self.manifest.python.dependencies
        if not dependency_file:
            return
        requirements = self.plugin_dir / dependency_file
        content = requirements.read_text(encoding="utf-8")
        effective = [line.strip() for line in content.splitlines() if line.strip() and not line.lstrip().startswith("#")]
        digest = hashlib.sha256(content.encode()).hexdigest()
        marker = self.runtime_dir / "requirements.sha256"
        if marker.is_file() and marker.read_text(encoding="ascii").strip() == digest:
            return
        if self.manifest.is_legacy:
            for line in effective:
                lowered = line.lower()
                if any(value in lowered for value in ("git+", "file:", "-e ", "--editable", "--index-url", "--extra-index-url")):
                    raise PluginError("Plugin dependency lock contains a forbidden source")
                if "==" not in line or "--hash=sha256:" not in line:
                    raise PluginError("Plugin dependencies must be pinned with SHA-256 hashes")
        if effective:
            options = ["--require-hashes", "--no-deps"] if self.manifest.is_legacy else []
            process = await asyncio.create_subprocess_exec(
                str(python), "-I", "-m", "pip", "--disable-pip-version-check", "install", *options, "--requirement", str(requirements),
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
                raise PluginError("Plugin dependency installation failed: " + self._sanitize(message)[-500:])
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
                            future.set_exception(PluginError(self._sanitize(str(message["error"].get("message", "Plugin error")))))
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
            method = message.get("method")
            if method not in {"capability.call", "core.call"} or (self.manifest.is_legacy and method != "capability.call"):
                raise PluginCapabilityError("Unsupported plugin call")
            params = message.get("params") or {}
            if not isinstance(params, dict):
                raise PluginCapabilityError("Invalid plugin call parameters")
            capability = str(params.get("capability", "")) if method == "capability.call" else str(params.get("method", ""))
            result = await self.capability_handler(capability, params)
            await self._write({"jsonrpc": "2.0", "id": identifier, "result": result})
        except Exception as error:
            await self._write({"jsonrpc": "2.0", "id": identifier, "error": {"code": "CAPABILITY_DENIED", "message": self._sanitize(str(error))[:500]}})

    async def _stderr(self) -> None:
        assert self.process and self.process.stderr
        while chunk := await self.process.stderr.read(1024):
            text = chunk.decode("utf-8", "replace")
            text = self._sanitize(text)
            self.stderr_tail = (self.stderr_tail + text)[-4096:]

    def state(self) -> str:
        if not self.process:
            return "stopped"
        return "running" if self.process.returncode is None else "error"


class InProcessPlugin:
    """Trusted, opt-in v2 runtime using the same public SDK registration API.

    Python cannot safely kill a running thread. Stop therefore drains calls and
    reports a timeout; operators may need to restart Core for a stuck plugin.
    """

    def __init__(self, manifest: PluginManifest, plugin_dir: Path, runtime_dir: Path, capability_handler: CapabilityHandler):
        if manifest.is_legacy:
            raise PluginError("Legacy plugins only support isolated runtime")
        self.manifest, self.plugin_dir, self.runtime_dir = manifest, plugin_dir, runtime_dir
        self.capability_handler = capability_handler
        self.registrations: list[dict[str, Any]] = []
        self.api = None
        self.context = None
        self.module = None
        self.active: set[asyncio.Task] = set()
        self.calls: dict[str, Any] = {}
        self.running = False
        self.draining = False

    async def start(self, timeout: float = 10, context: dict[str, Any] | None = None) -> None:
        if self.running:
            return
        try:
            import maintune_plugin_sdk  # noqa: F401
        except ModuleNotFoundError:
            source_sdk = Path(__file__).resolve().parents[2] / "sdk"
            if not (source_sdk / "maintune_plugin_sdk" / "api.py").is_file():
                raise PluginError("Maintune Plugin SDK is not installed")
            sys.path.insert(0, str(source_sdk))
        from maintune_plugin_sdk import PluginAPI, PluginContext

        source = self.plugin_dir / "src"
        relative = Path(*self.manifest.entrypoint.python.split("."))
        candidate = source / relative.with_suffix(".py")
        package = source / relative / "__init__.py"
        path = candidate if candidate.is_file() else package
        if not path.is_file():
            raise PluginError("Plugin entrypoint is missing")
        unique = "_maintune_plugin_" + hashlib.sha256(f"{self.manifest.id}:{self.manifest.version}".encode()).hexdigest()[:16]
        spec = importlib.util.spec_from_file_location(unique, path, submodule_search_locations=[str(path.parent)] if path == package else None)
        if not spec or not spec.loader:
            raise PluginError("Plugin entrypoint cannot be loaded")
        module = importlib.util.module_from_spec(spec)
        sys.modules[unique] = module
        try:
            await asyncio.wait_for(asyncio.to_thread(spec.loader.exec_module, module), timeout)
            register = getattr(module, "register", None)
            if not callable(register):
                raise PluginError("Plugin entrypoint must define register(api)")
            api = PluginAPI()
            result = register(api)
            if asyncio.iscoroutine(result):
                await asyncio.wait_for(result, timeout)
            self.api = api
            self.module = module
            config = context or {}
            data_dir = Path(config.get("data_dir") or self.runtime_dir / "data")
            data_dir.mkdir(parents=True, exist_ok=True)
            async def core_call(method: str, params: dict[str, Any]):
                return await self.capability_handler(method, {"params": params})
            self.context = PluginContext(
                plugin_id=self.manifest.id,
                plugin_version=self.manifest.version,
                data_dir=data_dir,
                config=config.get("config") or {},
                _core_call=core_call,
            )
            self.registrations = api.registrations()
            self.running = True
            self.draining = False
        except Exception:
            sys.modules.pop(unique, None)
            raise

    async def request(self, method: str, params: dict[str, Any], timeout: float = 10) -> Any:
        if not self.running or self.draining:
            raise PluginError("Plugin is not running")
        if method == "health":
            return {"ok": True, "protocol": PLUGIN_PROTOCOL_V2}
        if method == "config.migrate":
            previous = params.get("old_config") or {}
            if not isinstance(previous, dict):
                raise PluginError("Previous plugin config must be an object")
            migrate = getattr(self.module, "migrate_config", None)
            result = migrate(previous, str(params.get("old_version", "")), str(params.get("new_version", ""))) if callable(migrate) else previous
            if asyncio.iscoroutine(result):
                result = await asyncio.wait_for(result, timeout)
            if not isinstance(result, dict):
                raise PluginError("Plugin config migration must return an object")
            return result
        if method == "lifecycle.upgrade":
            upgrade = getattr(self.module, "on_upgrade", None)
            if callable(upgrade):
                result = upgrade(self.context, str(params.get("old_version", "")), str(params.get("new_version", "")))
                if asyncio.iscoroutine(result):
                    await asyncio.wait_for(result, timeout)
            return {"upgraded": True}
        if method != "extension.invoke" or not self.api or not self.context:
            raise PluginError("Unsupported in-process Plugin API method")
        from maintune_plugin_sdk import PluginContext

        invocation_id = str(params.get("invocation_id", ""))
        context = PluginContext(
            plugin_id=self.context.plugin_id,
            plugin_version=self.context.plugin_version,
            data_dir=self.context.data_dir,
            config=self.context.config,
            invocation_id=invocation_id,
            _core_call=self.context._core_call,
        )
        async def invoke():
            return await self.api.invoke(str(params.get("kind")), str(params.get("name")), context, params.get("input") or {})
        task = asyncio.create_task(invoke())
        self.active.add(task)
        self.calls[invocation_id] = context
        try:
            return await asyncio.wait_for(task, timeout)
        finally:
            self.active.discard(task)
            self.calls.pop(invocation_id, None)

    async def notify(self, method: str, params: dict[str, Any]) -> None:
        if method == "extension.cancel":
            context = self.calls.get(str(params.get("invocation_id", "")))
            if context:
                context._cancelled.set()

    async def stop(self) -> None:
        if not self.running:
            return
        self.draining = True
        if self.active:
            _, pending = await asyncio.wait(self.active, timeout=5)
            if pending:
                raise PluginError("In-process plugin did not drain; Core restart may be required")
        stop = getattr(self.module, "stop", None)
        if callable(stop):
            result = stop(self.context)
            if asyncio.iscoroutine(result):
                await asyncio.wait_for(result, 5)
        self.running = False

    def state(self) -> str:
        return "running" if self.running and not self.draining else "stopped"


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

    @staticmethod
    def _short_task_reference(task_id: str, task_ids: list[str]) -> str:
        minimum = min(8, len(task_id))
        for length in range(minimum, len(task_id) + 1):
            candidate = task_id[:length]
            if sum(value.startswith(candidate) for value in task_ids) == 1:
                return candidate
        return task_id

    @staticmethod
    def _resolve_task(db, reference: str) -> Task:
        exact = db.get(Task, reference)
        if exact:
            return exact
        if not re.fullmatch(r"[a-f0-9-]{8,36}", reference):
            raise PluginCapabilityError("Task not found")
        matches = list(db.scalars(select(Task).where(Task.id.startswith(reference)).limit(2)))
        if not matches:
            raise PluginCapabilityError("Task not found")
        if len(matches) != 1:
            raise PluginCapabilityError("Task reference is ambiguous")
        return matches[0]

    def _task_view(self, task: Task, task_ids: list[str]) -> dict[str, Any]:
        return {"id": task.id, "ref": self._short_task_reference(task.id, task_ids), "kind": task.kind, "repository": task.repository, "number": task.number, "status": task.status, "created": task.created, "updated": task.updated, "title": task.data.get("title") or task.data.get("summary") or ""}

    def _task_read(self, action: str, params: dict[str, Any]) -> Any:
        with self.sessions() as db:
            if action == "status":
                rows = list(db.scalars(select(Task)))
                return {"status": "ok", "counts": {"running": sum(row.status == "running" for row in rows), "waiting_for_owner": sum(row.status == "waiting_for_owner" for row in rows), "failed": sum(row.status.startswith("failed_") for row in rows)}}
            if action == "list":
                limit = min(max(int(params.get("limit", 20)), 1), 100)
                task_ids = list(db.scalars(select(Task.id)))
                return [self._task_view(row, task_ids) for row in db.scalars(select(Task).order_by(Task.created.desc()).limit(limit))]
            if action == "get":
                row = self._resolve_task(db, str(params.get("task_id", "")))
                task_ids = list(db.scalars(select(Task.id)))
                timeline = list(db.scalars(select(Timeline).where(Timeline.task_id == row.id).order_by(Timeline.timestamp)))
                return {**self._task_view(row, task_ids), "summary": row.data.get("summary", ""), "timeline": [{"timestamp": item.timestamp, "kind": item.kind, "data": item.data} for item in timeline[-50:]]}
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
            task = self._resolve_task(db, task_id)
            if task.status != "waiting_for_owner":
                raise PluginCapabilityError("Task is not waiting for owner")
            normalized = owner_action(decision_action, decision_action)
            task.status = "queued"
            task.data = {**task.data, "owner_decision": f"Plugin decision: {normalized}", "owner_decision_action": normalized, "owner_decision_source": self.plugin_id}
            db.add(Timeline(task_id=task.id, kind="owner_decision", data={"action": normalized, "source": self.plugin_id}))
            db.add(Config(id=replay_id, data={"created": time.time(), "task_id": task.id, "action": normalized}))
        return {"status": "queued", "action": normalized}


def make_event(event: str, task: Task | None = None, data: dict[str, Any] | None = None, task_ref: str | None = None) -> PluginEvent:
    safe_data = dict(data or {})
    for key in list(safe_data):
        if any(word in key.lower() for word in ("secret", "token", "password", "prompt", "private_key", "credential")):
            safe_data.pop(key)
    return PluginEvent(
        event=event,
        event_id="evt_" + uuid.uuid4().hex,
        timestamp=datetime.now(UTC).isoformat(),
        repository=task.repository if task else None,
        task={"id": task.id, "ref": task_ref or task.id[:8], "kind": task.kind, "number": task.number, "status": task.status, "title": task.data.get("title") or task.data.get("summary") or ""} if task else None,
        data=safe_data,
    )


def generate_bridge_token() -> str:
    return secrets.token_urlsafe(48)
