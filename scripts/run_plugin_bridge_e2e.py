from __future__ import annotations

import argparse
import asyncio
import sys
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet

from maintainer.db import Task, database
from maintainer.plugin_manager import PluginManager
from maintainer.plugin_system import make_event
from maintainer.security import Vault


class FakeWebSocket:
    def __init__(self):
        self.messages: list[dict] = []

    async def send_json(self, value: dict):
        self.messages.append(value)


async def main(mtp: Path, astrbot_plugin: Path) -> None:
    sys.path.insert(0, str(astrbot_plugin))
    from maintune_bridge.auth import CommandContext, authorize
    from maintune_bridge.commands import parse_command
    from maintune_bridge.dedupe import EventDeduplicator

    with tempfile.TemporaryDirectory(prefix="maintune-plugin-e2e-") as temporary:
        root = Path(temporary)
        engine, sessions = database(f"sqlite:///{root / 'app.db'}")
        vault = Vault(Fernet.generate_key().decode())
        manager = PluginManager(root / "plugins", "0.1.0-preview.2", sessions, vault)
        inbox = manager.packages.inbox / mtp.name
        inbox.write_bytes(mtp.read_bytes())
        installed = manager.install(mtp.name)
        assert installed["id"] == "official.astrbot-bridge"
        token = manager.regenerate_secret(installed["id"], "bridge_token")
        await manager.enable(installed["id"])

        with sessions.begin() as db:
            started = Task(kind="issue", repository="example/repository", number=1, event="issues.opened", delivery_id="e2e-started", status="running", data={"summary": "Started task"})
            waiting = Task(kind="issue", repository="example/repository", number=2, event="issues.opened", delivery_id="e2e-waiting", status="waiting_for_owner", data={"summary": "Owner decision"})
            db.add_all([started, waiting])
            db.flush()
            started_id, waiting_id = started.id, waiting.id

        auth = {"protocol": "maintune.astrbot.v1", "type": "authenticate", "token": token, "instance": "fake-astrbot"}
        assert await manager.authenticate_transport(installed["id"], auth)
        socket = FakeWebSocket()
        await manager.connect(installed["id"], socket, auth)
        assert socket.messages[-1]["type"] == "hello"

        with sessions() as db:
            started_task = db.get(Task, started_id)
            waiting_task = db.get(Task, waiting_id)
            started_event = make_event("task.started", started_task)
            waiting_event = make_event("task.waiting_for_owner", waiting_task)
        await manager.publish(started_event)
        await manager.publish(waiting_event)

        dedupe = EventDeduplicator(root / "astrbot-event-ids.json")
        qq_messages: list[str] = []
        for frame in socket.messages:
            if frame.get("type") != "event":
                continue
            event = frame["event"]
            if not dedupe.seen(event["event_id"]):
                qq_messages.append(event["event"])
                dedupe.add(event["event_id"])
            await manager.transport_message(installed["id"], {"protocol": "maintune.astrbot.v1", "type": "ack", "event_id": event["event_id"]})
        assert qq_messages == ["task.started", "task.waiting_for_owner"]

        # At-least-once replay must not duplicate a QQ notification.
        duplicate = {"protocol": "maintune.astrbot.v1", "type": "event", "event": waiting_event.model_dump()}
        event = duplicate["event"]
        if not dedupe.seen(event["event_id"]):
            qq_messages.append(event["event"])
        assert qq_messages.count("task.waiting_for_owner") == 1

        empty_users, empty_groups = frozenset(), frozenset()
        assert not authorize(CommandContext("100", False), empty_users, empty_groups)
        assert authorize(CommandContext("100", True), empty_users, empty_groups)
        assert not authorize(CommandContext("100", True, "200"), empty_users, empty_groups)
        assert authorize(CommandContext("100", False, "200"), frozenset({"100"}), frozenset({"200"}))

        status = parse_command("/maintune status")
        response = await manager.transport_message(installed["id"], {"protocol": "maintune.astrbot.v1", "type": "request", "request_id": "status-0001", "action": status.action, "params": {}})
        assert response[0]["type"] == "response" and response[0]["data"]["status"] == "ok"
        detail = parse_command(f"/maintune task {waiting_id}")
        response = await manager.transport_message(installed["id"], {"protocol": "maintune.astrbot.v1", "type": "request", "request_id": "task-00001", "action": detail.action, "params": {"task_id": detail.task_id}})
        assert response[0]["data"]["id"] == waiting_id
        decision = parse_command(f"/maintune implement {waiting_id}")
        response = await manager.transport_message(installed["id"], {"protocol": "maintune.astrbot.v1", "type": "request", "request_id": "decision-0001", "action": decision.action, "params": {"task_id": decision.task_id, "decision": decision.decision}})
        assert response[0]["data"] == {"status": "queued", "action": "implement"}
        with sessions() as db:
            assert db.get(Task, waiting_id).data["owner_decision_action"] == "implement"
        replay = await manager.transport_message(installed["id"], {"protocol": "maintune.astrbot.v1", "type": "request", "request_id": "decision-0001", "action": "owner_decision", "params": {"task_id": waiting_id, "decision": "implement"}})
        assert replay[0]["type"] == "error" and replay[0]["code"] == "CAPABILITY_FAILED"

        await manager.disconnect(installed["id"], socket)
        await manager.stop()
        engine.dispose()
        print("plugin-bridge-e2e: PASS")
        print("notifications=2 unauthorized=denied admin_private=allowed admin_group=denied allowed_group=allowed")
        print("status=ok task_detail=ok owner_decision=implement replay=denied duplicate_event=deduped")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mtp", type=Path, required=True)
    parser.add_argument("--astrbot-plugin", type=Path, required=True)
    arguments = parser.parse_args()
    asyncio.run(main(arguments.mtp.resolve(), arguments.astrbot_plugin.resolve()))
