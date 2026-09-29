# maintune-plugin-sdk

Public Python SDK for Maintune Plugin API v2. It requires Python 3.12 or later
and has no runtime dependency on Maintune Core or third-party packages.

This package is independently buildable under the MIT License. While Stable
preparation is in progress, build a wheel from this directory with
`python -m pip wheel --no-deps --wheel-dir dist .`, then install that wheel in a
clean Python 3.12 environment. Do not assume the package is available from
PyPI until a separate publication is verified. The host also stages this SDK
into each isolated v2 plugin environment.

The [developer guide](https://github.com/mcxianyujun/maintune/blob/main/docs/plugin-api-v2.md) and
[API reference](https://github.com/mcxianyujun/maintune/blob/main/docs/plugin-api-reference.md) describe the public
host-side contracts and capability boundaries. Installing the SDK alone does
not grant a plugin permission to read tasks or write to GitHub.

The isolated runtime launches `python -m maintune_plugin_sdk.runner` in the
plugin's own environment. Core and the runner exchange UTF-8, newline-delimited
JSON-RPC 2.0 messages over stdio. Plugin `print` and logging output go to
stderr; stdout is reserved for protocol messages.

## Register extensions

An entrypoint module exports `register(api)`. The same registrations can be
used by an in-process host.

```python
from maintune_plugin_sdk import PluginContext


def register(api):
    api.register_hook("task.started", on_task_started)
    api.on_task_finally(on_task_finally)
    api.register_tool("search", search, description="Search the configured index")
    api.register_service("lookup", lookup)


async def on_task_started(context: PluginContext, payload: dict):
    context.logger.info("Task started")


async def on_task_finally(context: PluginContext, payload: dict):
    context.logger.info("Task finished")


async def search(context: PluginContext, query: str, limit: int = 5) -> dict:
    return {"query": query, "limit": limit}


def lookup(context: PluginContext, payload: dict) -> dict:
    return {"found": False}
```

Hooks, services, model providers, and sandbox providers receive their input as
one JSON object. Tool handlers receive only the model-supplied named arguments
plus an optional first `context` or `ctx` parameter. The context exposes
plugin identity, configured data directory, config, stable invocation ID,
optional task/agent IDs, documented Core calls, and advisory cancellation:

```python
async def long_tool(context: PluginContext, query: str) -> str:
    if context.cancelled:
        return "cancelled"
    # For a long-running wait, use await context.wait_cancelled().
    return query
```

The runner handles `extension.cancel` with an `invocation_id` by setting the
context's cancellation event. It does not forcibly interrupt the handler;
Core's watchdog remains the final timeout boundary.

## Tool schemas

The SDK infers a small JSON Schema object from type-annotated Tool parameters.
Supported annotations include `str`, `int`, `float`, `bool`, `Literal[...]`,
`list[T]`, and dictionaries with string keys. An optional parameter such as
`str | None = None` may be omitted by the caller. Explicit JSON `null` is not
part of the current Core schema subset. For complex inputs, pass an explicit
`input_schema` to `register_tool`.

Core assigns public namespaced IDs such as `<plugin-id>/search`; plugins
register only their local name. Recommended agents are metadata only and do
not enable a Tool automatically.

## Secrets and logs

Core marks secret config keys in `secret_fields` when starting the runner. The
runner redacts their values from stderr and error responses. The context's
representation omits config. Plugins should still avoid returning secrets as
Tool or Service results and should never log credentials intentionally.
