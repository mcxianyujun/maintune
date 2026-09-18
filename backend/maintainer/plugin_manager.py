from __future__ import annotations

import asyncio
import json
import secrets
import time
from pathlib import Path
from typing import Any

from fastapi import WebSocket
from sqlalchemy import select

from .db import Config, Task
from .plugin_system import (
    MAX_MESSAGE_BYTES,
    PLUGIN_PROTOCOL,
    PluginCapabilityBroker,
    PluginError,
    PluginEvent,
    PluginManifest,
    PluginPackageError,
    PluginPackageManager,
    PluginProcess,
    generate_bridge_token,
    load_manifest,
    make_event,
)


class PluginManager:
    def __init__(self, root: Path, maintune_version: str, sessions, vault):
        self.packages = PluginPackageManager(root, maintune_version)
        self.sessions = sessions
        self.vault = vault
        self.processes: dict[str, PluginProcess] = {}
        self.connections: dict[str, set[WebSocket]] = {}
        self.connection_state: dict[str, dict[str, Any]] = {}
        self.subscriptions: dict[str, set[str]] = {}
        self._heartbeat_task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self.restart_attempts: dict[str, int] = {}
        self.restart_after: dict[str, float] = {}

    def _config_id(self, plugin_id: str) -> str:
        return f"plugin:{plugin_id}"

    def _manifest(self, plugin_id: str) -> PluginManifest:
        path = self.packages.installed / plugin_id / "manifest.yaml"
        if not path.is_file():
            raise PluginPackageError("Plugin is not installed")
        return load_manifest(path)

    def _record(self, plugin_id: str) -> dict[str, Any]:
        with self.sessions() as db:
            row = db.get(Config, self._config_id(plugin_id))
            return dict(row.data) if row else {"enabled": False, "config": {}, "secrets": {}, "error": ""}

    def _save_record(self, plugin_id: str, data: dict[str, Any]) -> None:
        with self.sessions.begin() as db:
            row = db.get(Config, self._config_id(plugin_id))
            if row:
                row.data = data
            else:
                db.add(Config(id=self._config_id(plugin_id), data=data))

    async def start(self) -> None:
        self._stop.clear()
        for manifest in self.packages.discover():
            if self._record(manifest.id).get("enabled"):
                try:
                    await self.enable(manifest.id)
                except Exception as error:
                    record = self._record(manifest.id)
                    record["error"] = self._sanitize(str(error))
                    self._save_record(manifest.id, record)
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def stop(self) -> None:
        self._stop.set()
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        await asyncio.gather(*(process.stop() for process in list(self.processes.values())), return_exceptions=True)
        self.processes.clear()

    async def _heartbeat_loop(self) -> None:
        while not self._stop.is_set():
            await asyncio.sleep(15)
            for manifest in self.packages.discover():
                if not self._record(manifest.id).get("enabled") or manifest.id in self.processes:
                    continue
                if time.time() < self.restart_after.get(manifest.id, 0):
                    continue
                try:
                    await self.enable(manifest.id)
                    self.restart_attempts[manifest.id] = 0
                except Exception as error:
                    attempts = min(self.restart_attempts.get(manifest.id, 0) + 1, 6)
                    self.restart_attempts[manifest.id] = attempts
                    self.restart_after[manifest.id] = time.time() + min(2 ** attempts, 60)
                    record = self._record(manifest.id)
                    record["error"] = self._sanitize(str(error))
                    self._save_record(manifest.id, record)
            for plugin_id, process in list(self.processes.items()):
                try:
                    await process.request("health", {}, timeout=5)
                except Exception as error:
                    record = self._record(plugin_id)
                    record["error"] = self._sanitize(str(error))
                    self._save_record(plugin_id, record)
                    await process.stop()
                    self.processes.pop(plugin_id, None)
                    attempts = min(self.restart_attempts.get(plugin_id, 0) + 1, 6)
                    self.restart_attempts[plugin_id] = attempts
                    self.restart_after[plugin_id] = time.time() + min(2 ** attempts, 60)

    def scan(self) -> list[dict[str, Any]]:
        results = []
        for archive in sorted(self.packages.inbox.glob("*.mtp")):
            try:
                manifest = self.packages.validate(archive)
                results.append({"file": archive.name, "valid": True, "manifest": manifest.model_dump()})
            except Exception as error:
                results.append({"file": archive.name, "valid": False, "error": self._sanitize(str(error))})
        return results

    def install(self, filename: str) -> dict[str, Any]:
        if Path(filename).name != filename:
            raise PluginPackageError("Invalid package filename")
        manifest = self.packages.install(self.packages.inbox / filename)
        config: dict[str, Any] = {}
        for name, field in manifest.config.items():
            if field.type != "secret" and field.default is not None:
                config[name] = field.default
        self._save_record(manifest.id, {"enabled": False, "config": config, "secrets": {}, "error": "", "installed_at": time.time()})
        return self.view(manifest.id)

    async def enable(self, plugin_id: str) -> dict[str, Any]:
        manifest = self._manifest(plugin_id)
        record = self._record(plugin_id)
        missing = [name for name, field in manifest.config.items() if field.required and not (record.get("secrets", {}).get(name) if field.type == "secret" else record.get("config", {}).get(name))]
        if missing:
            raise PluginError("Required plugin configuration is missing: " + ", ".join(missing))
        if plugin_id not in self.processes:
            broker = PluginCapabilityBroker(self.sessions, plugin_id, set(manifest.capabilities))
            async def capability(capability: str, params: dict[str, Any]):
                result = await broker.call(capability, params)
                if capability == "event.subscribe" and params.get("action") == "subscribe":
                    self.set_subscriptions(plugin_id, list(params.get("events") or []))
                return result
            process = PluginProcess(manifest, self.packages.installed / plugin_id, self.packages.runtime / plugin_id, capability)
            await process.start()
            self.processes[plugin_id] = process
        record.update({"enabled": True, "error": ""})
        self._save_record(plugin_id, record)
        return self.view(plugin_id)

    async def _stop_runtime(self, plugin_id: str) -> None:
        sockets = list(self.connections.pop(plugin_id, set()))
        self.connection_state.pop(plugin_id, None)
        self.subscriptions.pop(plugin_id, None)
        for socket in sockets:
            try:
                await socket.close(code=1012)
            except Exception:
                pass
        process = self.processes.pop(plugin_id, None)
        if process:
            await process.stop()

    async def disable(self, plugin_id: str) -> dict[str, Any]:
        await self._stop_runtime(plugin_id)
        record = self._record(plugin_id)
        record["enabled"] = False
        self._save_record(plugin_id, record)
        return self.view(plugin_id)

    async def reload(self, plugin_id: str) -> dict[str, Any]:
        if not self._record(plugin_id).get("enabled"):
            raise PluginError("Plugin is disabled")
        await self._stop_runtime(plugin_id)
        try:
            return await self.enable(plugin_id)
        except Exception as error:
            record = self._record(plugin_id)
            record["error"] = self._sanitize(str(error))
            self._save_record(plugin_id, record)
            raise

    async def uninstall(self, plugin_id: str) -> None:
        await self.disable(plugin_id)
        self.packages.uninstall(plugin_id)
        with self.sessions.begin() as db:
            row = db.get(Config, self._config_id(plugin_id))
            if row:
                db.delete(row)

    def configure(self, plugin_id: str, values: dict[str, Any]) -> dict[str, Any]:
        manifest = self._manifest(plugin_id)
        unknown = set(values) - set(manifest.config)
        if unknown:
            raise PluginError("Unknown plugin configuration field")
        record = self._record(plugin_id)
        config, encrypted = dict(record.get("config", {})), dict(record.get("secrets", {}))
        for name, value in values.items():
            field = manifest.config[name]
            if field.type == "secret":
                if value not in (None, "", "********"):
                    encrypted[name] = self.vault.encrypt(str(value))
                continue
            config[name] = self._validate_value(field.type, value, field.options)
        record.update({"config": config, "secrets": encrypted, "error": ""})
        self._save_record(plugin_id, record)
        return self.view(plugin_id)

    def regenerate_secret(self, plugin_id: str, field_name: str) -> str:
        manifest = self._manifest(plugin_id)
        field = manifest.config.get(field_name)
        if not field or field.type != "secret":
            raise PluginError("Secret field not found")
        value = generate_bridge_token()
        record = self._record(plugin_id)
        encrypted = dict(record.get("secrets", {}))
        encrypted[field_name] = self.vault.encrypt(value)
        record["secrets"] = encrypted
        self._save_record(plugin_id, record)
        return value

    def _validate_value(self, kind: str, value: Any, options: list[str]) -> Any:
        if kind == "string":
            if not isinstance(value, str) or len(value) > 4000:
                raise PluginError("Invalid string configuration")
        elif kind == "boolean":
            if not isinstance(value, bool):
                raise PluginError("Invalid boolean configuration")
        elif kind == "integer":
            if not isinstance(value, int) or isinstance(value, bool):
                raise PluginError("Invalid integer configuration")
        elif kind == "select":
            if value not in options:
                raise PluginError("Invalid select configuration")
        elif kind == "string_list":
            if not isinstance(value, list) or len(value) > 100 or any(not isinstance(item, str) or len(item) > 500 for item in value):
                raise PluginError("Invalid string-list configuration")
        return value

    def list(self) -> list[dict[str, Any]]:
        return [self.view(manifest.id) for manifest in self.packages.discover()]

    def readme(self, plugin_id: str) -> str:
        self._manifest(plugin_id)
        root = (self.packages.installed / plugin_id).resolve()
        candidate = root / "README.md"
        path = candidate.resolve()
        if candidate.is_symlink() or path.parent != root or not path.is_file():
            raise PluginPackageError("Plugin README is not available")
        if path.stat().st_size > 512 * 1024:
            raise PluginPackageError("Plugin README is too large")
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError as error:
            raise PluginPackageError("Plugin README must be UTF-8") from error

    def view(self, plugin_id: str) -> dict[str, Any]:
        manifest = self._manifest(plugin_id)
        record = self._record(plugin_id)
        process = self.processes.get(plugin_id)
        config = dict(record.get("config", {}))
        for name, field in manifest.config.items():
            if field.type == "secret":
                config[name] = "********" if record.get("secrets", {}).get(name) else ""
        connection = self.connection_state.get(plugin_id, {})
        return {
            "id": manifest.id,
            "name": manifest.name,
            "version": manifest.version,
            "publisher": manifest.publisher,
            "license": manifest.license,
            "description": manifest.description,
            "api_version": manifest.api_version,
            "capabilities": manifest.capabilities,
            "config_schema": {key: value.model_dump() for key, value in manifest.config.items()},
            "config": config,
            "enabled": bool(record.get("enabled")),
            "runtime_status": process.state() if process else "stopped",
            "error": record.get("error", ""),
            "connection_status": "connected" if self.connections.get(plugin_id) else "disconnected",
            "connected_instance": connection.get("instance", ""),
            "last_heartbeat": connection.get("last_heartbeat"),
            "event_subscriptions": sorted(self.subscriptions.get(plugin_id, set())),
            "has_readme": (self.packages.installed / plugin_id / "README.md").is_file(),
        }

    def _secret(self, plugin_id: str, name: str) -> str:
        encrypted = self._record(plugin_id).get("secrets", {}).get(name)
        return self.vault.decrypt(encrypted) if encrypted else ""

    async def authenticate_transport(self, plugin_id: str, message: dict[str, Any]) -> bool:
        if message.get("protocol") != "maintune.astrbot.v1" or message.get("type") != "authenticate":
            return False
        supplied = str(message.get("token", ""))
        expected = self._secret(plugin_id, "bridge_token")
        return bool(expected) and secrets.compare_digest(supplied.encode(), expected.encode())

    async def connect(self, plugin_id: str, websocket: WebSocket, authenticate: dict[str, Any]) -> None:
        process = self.processes.get(plugin_id)
        if not process or process.state() != "running":
            raise PluginError("Plugin is not running")
        self.connections.setdefault(plugin_id, set()).add(websocket)
        self.connection_state[plugin_id] = {"instance": str(authenticate.get("instance", ""))[:200], "last_heartbeat": time.time()}
        result = await process.request("transport.connected", {key: value for key, value in authenticate.items() if key != "token"})
        await websocket.send_json(result or {"protocol": "maintune.astrbot.v1", "type": "hello", "timestamp": time.time()})
        for event in self._load_outbox(plugin_id).values():
            await websocket.send_json({"protocol": "maintune.astrbot.v1", "type": "event", "event": event})

    async def disconnect(self, plugin_id: str, websocket: WebSocket) -> None:
        self.connections.get(plugin_id, set()).discard(websocket)
        if not self.connections.get(plugin_id):
            self.connection_state.pop(plugin_id, None)
        process = self.processes.get(plugin_id)
        if process and process.state() == "running":
            await process.notify("transport.disconnected", {})

    async def transport_message(self, plugin_id: str, message: dict[str, Any]) -> list[dict[str, Any]]:
        process = self.processes.get(plugin_id)
        if not process:
            raise PluginError("Plugin is not running")
        if message.get("type") == "ack" and isinstance(message.get("event_id"), str):
            self._ack(plugin_id, message["event_id"])
        if message.get("type") == "heartbeat":
            state = self.connection_state.setdefault(plugin_id, {})
            state["last_heartbeat"] = time.time()
        result = await process.request("transport.message", message)
        if result is None:
            return []
        return result if isinstance(result, list) else [result]

    async def publish(self, event: PluginEvent) -> None:
        for manifest in self.packages.discover():
            if "event.subscribe" not in manifest.capabilities or not self._record(manifest.id).get("enabled"):
                continue
            subscribed = self.subscriptions.get(manifest.id)
            if subscribed and event.event not in subscribed:
                continue
            self._queue(manifest.id, event)
            payload = {"protocol": "maintune.astrbot.v1", "type": "event", "event": event.model_dump()}
            for websocket in list(self.connections.get(manifest.id, set())):
                try:
                    await websocket.send_json(payload)
                except Exception:
                    self.connections.get(manifest.id, set()).discard(websocket)

    async def publish_task(self, event: str, task_id: str, data: dict[str, Any] | None = None) -> None:
        with self.sessions() as db:
            task = db.get(Task, task_id)
            if task:
                task_ids = list(db.scalars(select(Task.id)))
                reference = PluginCapabilityBroker._short_task_reference(task.id, task_ids)
                await self.publish(make_event(event, task, data, reference))

    def set_subscriptions(self, plugin_id: str, events: list[str]) -> None:
        self.subscriptions[plugin_id] = {event for event in events if isinstance(event, str) and len(event) <= 80}

    def _outbox_path(self, plugin_id: str) -> Path:
        path = self.packages.runtime / plugin_id
        path.mkdir(parents=True, exist_ok=True)
        return path / "event-outbox.json"

    def _load_outbox(self, plugin_id: str) -> dict[str, dict[str, Any]]:
        path = self._outbox_path(plugin_id)
        if not path.is_file():
            return {}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except Exception:
            return {}

    def _write_outbox(self, plugin_id: str, events: dict[str, dict[str, Any]]) -> None:
        path = self._outbox_path(plugin_id)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(events, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        temporary.replace(path)

    def _queue(self, plugin_id: str, event: PluginEvent) -> None:
        events = self._load_outbox(plugin_id)
        events[event.event_id] = event.model_dump()
        if len(events) > 1000:
            events.pop(next(iter(events)))
        self._write_outbox(plugin_id, events)

    def _ack(self, plugin_id: str, event_id: str) -> None:
        events = self._load_outbox(plugin_id)
        if events.pop(event_id, None) is not None:
            self._write_outbox(plugin_id, events)

    @staticmethod
    def _sanitize(message: str) -> str:
        return message.replace("\n", " ")[:500]
