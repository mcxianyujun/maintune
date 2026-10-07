"""Run with only the public SDK installed; no Maintune Core imports."""
import asyncio
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from maintune_plugin_sdk import PluginAPI, PluginContext

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
import workflow_notes as plugin
from build_mtp import MEMBERS, build


class MinimalExampleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.context = PluginContext("example.workflow-notes", "0.1.0-dev", self.directory,
                                     {"label": "Demo", "demo_secret": "TEST_ONLY_SECRET"})
        self.api = PluginAPI()
        plugin.register(self.api)

    def test_public_registration_and_typed_tool(self):
        items = self.api.registrations()
        self.assertEqual([(i["kind"], i["name"]) for i in items],
                         [("hook", "task.started"), ("tool", "add")])
        tool = items[1]
        self.assertEqual(tool["input_schema"], {
            "type": "object", "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
            "required": ["a", "b"], "additionalProperties": False})
        self.assertEqual(tool["recommended_agents"], ["code_worker"])
        self.assertEqual(asyncio.run(self.api.invoke("tool", "add", self.context, {"a": -2, "b": 5})),
                         {"label": "Demo", "total": 3})

    def test_notification_hook_persists_only_bounded_public_data(self):
        result = asyncio.run(self.api.invoke("hook", "task.started", self.context,
                                            {"task_id": "x" * 100, "untrusted": "discard me"}))
        self.assertIsNone(result)
        record = json.loads((self.directory / "last-task.json").read_text())
        self.assertEqual(record, {"task_id": "x" * 64})
        asyncio.run(self.api.invoke("hook", "task.started", self.context, {"task_id": "next"}))
        self.assertEqual(json.loads((self.directory / "last-task.json").read_text()), {"task_id": "next"})

    def test_secret_never_returned_or_persisted_and_stop_preserves_data(self):
        asyncio.run(self.api.invoke("hook", "task.started", self.context, {"task_id": "public-task"}))
        result = asyncio.run(self.api.invoke("tool", "add", self.context, {"a": 1, "b": 2}))
        plugin.stop(self.context)
        text = json.dumps(result) + (self.directory / "last-task.json").read_text() + repr(self.context)
        self.assertNotIn("TEST_ONLY_SECRET", text)

    def test_package_is_deterministic_and_allowlisted(self):
        one, two = self.directory / "one.mtp", self.directory / "two.mtp"
        build(one)
        build(two)
        self.assertEqual(one.read_bytes(), two.read_bytes())
        with zipfile.ZipFile(one) as archive:
            self.assertEqual(archive.namelist(), list(MEMBERS))
            self.assertIsNone(archive.testzip())
            manifest = json.loads(archive.read("manifest.yaml"))
            self.assertEqual(manifest["runtime"], {"default": "isolated", "supported": ["isolated"]})
            self.assertEqual(manifest["plugin_api"], 2)
            self.assertTrue(manifest["config_schema"]["properties"]["demo_secret"]["secret"])
            self.assertNotIn("dependencies", manifest)
            self.assertNotIn("ui", manifest)
            self.assertIn("AGPL", archive.read("LICENSE").decode())


if __name__ == "__main__":
    unittest.main()
