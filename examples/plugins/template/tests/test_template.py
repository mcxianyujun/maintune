"""Offline contract checks for the template and its package builder."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from maintune_plugin_sdk import PluginAPI, PluginContext  # noqa: E402
import main as plugin  # noqa: E402
from build_mtp import MEMBERS, build  # noqa: E402


class TemplateTests(unittest.TestCase):
    def test_registers_tool_and_invokes_it(self):
        api = PluginAPI()
        plugin.register(api)
        registration = api.registrations()[0]
        self.assertEqual((registration["kind"], registration["name"]), ("tool", "greet"))
        self.assertEqual(registration["input_schema"]["required"], ["name"])
        with tempfile.TemporaryDirectory() as temporary:
            context = PluginContext("yourname.hello-plugin", "0.1.0", Path(temporary), {})
            result = asyncio.run(api.invoke("tool", "greet", context, {"name": "Maintune"}))
        self.assertEqual(result, {"message": "Hello, Maintune!"})

    def test_manifest_and_build_are_valid_and_reproducible(self):
        manifest = json.loads((ROOT / "manifest.yaml").read_text(encoding="utf-8"))
        self.assertEqual(manifest["plugin_api"], 2)
        self.assertEqual(manifest["runtime"]["default"], "isolated")
        with tempfile.TemporaryDirectory() as temporary:
            first, second = Path(temporary) / "one.mtp", Path(temporary) / "two.mtp"
            build(first)
            build(second)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            with zipfile.ZipFile(first) as archive:
                self.assertEqual(tuple(archive.namelist()), MEMBERS)
                self.assertEqual(json.loads(archive.read("manifest.yaml"))["id"], manifest["id"])


if __name__ == "__main__":
    unittest.main()
