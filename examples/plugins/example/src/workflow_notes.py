"""Minimal reference; only the public SDK and Python standard library."""

import json

from maintune_plugin_sdk import PluginAPI, PluginContext


def on_task_started(context: PluginContext, payload: dict) -> None:
    # Notification Hook: observe, return None, never change a workflow decision.
    # Save only a bounded public task ID, never the full payload or config.
    record = {"task_id": str(payload.get("task_id", ""))[:64]}
    (context.data_dir / "last-task.json").write_text(
        json.dumps(record), encoding="utf-8",
    )


def add(context: PluginContext, a: int, b: int) -> dict:
    # demo_secret illustrates encrypted config, not a network credential.
    # It is intentionally never returned, logged or persisted by this example.
    return {"label": context.config.get("label", "Example"), "total": a + b}


def register(api: PluginAPI) -> None:
    # Called when the isolated process starts on enable/reload.
    api.register_hook("task.started", on_task_started)
    api.register_tool(
        "add", add, description="Add two integers (developer reference only).",
        recommended_agents=["code_worker"],
    )


def stop(context: PluginContext) -> None:
    # Optional SDK stop callback; no background resources need cleanup here.
    # Core preserves data_dir and config when disabled.
    pass
