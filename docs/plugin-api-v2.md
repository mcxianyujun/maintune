# Maintune Plugin API v2 — developer guide

Plugin API v2 was released in `v0.1.0-preview.3`. This guide documents that
preview contract; Stable preparation may tighten documentation and packaging
without promising unimplemented extension points. The
[v1 API](plugin-system.md) remains supported as Legacy, with no announced
removal date. See the [Python API reference](plugin-api-reference.md) for
signatures, Core calls, and compatibility boundaries.

## Scope and trust

An installed, enabled plugin is trusted code chosen by the instance owner.
The host still keeps raw GitHub App keys, installation tokens, administrator
credentials, and other Core secrets. Plugins interact with the host through
documented API methods; imports from `maintainer.*` are not public contracts.
There is no marketplace or plugin signing in Preview 3.

## Start with a package

The extension remains `.mtp` (a ZIP archive). A v2 package supplies
`manifest.yaml`, its `src/` entrypoint, and optionally `README.md`, a standard
Python dependency file, and UI assets. `plugin_api: 2` selects v2. The legacy
`api_version: 1` field selects v1. Keep the manifest about **loading**, not a
second list of runtime Hook, Tool, Service, or Provider registrations.

```yaml
id: example.search
name: Search Example
version: 0.1.0-dev
plugin_api: 2
publisher: mcxianyujun
license: MIT
maintune:
  min_version: 0.1.0
runtime:
  default: isolated
  supported: [isolated]
entrypoint:
  python: search_plugin
python:
  dependencies: requirements.txt
```

The current manifest parser also accepts an optional `maintune.max_version`,
Maintune plugin `dependencies` (required or optional), `config_schema`, and an
optional `ui` declaration. Python dependencies use a normal requirements file;
custom install scripts are rejected. The package validator checks archive
paths, symlinks, size and file counts, manifest shape, and entrypoint presence
before extraction. `isolated` is the default. `in_process` is an advanced
runtime option under development; imports of Core internals from that runtime
remain unsupported even if Python permits them.

## SDK, lifecycle, and transport

The lightweight `maintune-plugin-sdk` package contains the public
`PluginAPI` and `PluginContext` types, schema helpers, and a stdio JSON-RPC
runner. It can be installed without installing Maintune Core. An entrypoint
defines `register(api)` and registers handlers when the host starts it:

```python
from maintune_plugin_sdk import PluginAPI

def register(api: PluginAPI) -> None:
    api.register_tool("search", search, description="Search public pages")

async def search(query: str) -> dict:
    return {"query": query, "results": []}
```

The host assigns the public ID `example.search/search`; extension names are
always scoped to the package ID. A handler may accept a leading
`context: PluginContext` argument. Context exposes plugin ID/version,
`data_dir`, validated config, `invocation_id`,
advisory cancellation, and documented `call_core(...)` methods. It does not
contain ORM, Controller, or GitHub credential objects.
Preview 3 does not provide task or Agent IDs on `PluginContext`; Hooks carry
task IDs in their validated input when applicable.

Preview 3's formal isolated transport is newline-delimited JSON-RPC 2.0 over
stdio. Messages are bounded to 1 MiB. The protocol is language neutral so a
future implementation can use another language; no additional HTTP, socket,
or gRPC transport is promised in this release. Isolated plugins use their own
Python process and environment. The lifecycle supports start, health, stop,
and extension invocation. A plugin crash is reported on that plugin rather
than terminating Core.

## Runtime registrations

Registrations happen in `register(api)`, not in the manifest. The in-tree SDK
currently provides `register_hook`, `on_task_finally`, `register_tool`,
`register_service`, `register_model_provider`,
`register_sandbox_provider`, and `register_route`. Registration names become
`<plugin-id>/<name>` in Core. Duplicate names and invalid metadata are
rejected. The registry is an interface boundary; each extension needs its
own end-to-end gate before being described as operational in production.

### Hook catalog

| Hook | Stability | Type | Order/failure | Purpose |
| --- | --- | --- | --- | --- |
| `task.started` | Stable | Notification | Parallel, fail open | Observe task start. |
| `task.finally` | Stable | Notification/finalizer | Serial, fail open | Observe a genuinely finished task. |
| `issue.analysis_prompt` | Experimental | Pipeline | Serial, fail open | Adjust the Issue analysis prompt before the next plugin sees it. |
| `pr.review` | Experimental | Replaceable | Serial, fail open | Return a structured replacement review, or continue/cancel/wait. |

Hook behavior, timeout, retry safety, schema, and ordering belong to each
catalog entry. Serial modifiable Hooks must pass each validated result to the
next plugin; invalid output cannot flow onward. Priority orders different
plugins, with load order resolving equal priorities. The Issue prompt Hook's
timeline records hashes of its input and output plus step status, without
storing full prompt text. `task.finally` is an
independent task lifecycle finalizer: ordinary Hook cancellation cannot skip
it. If execution is physically impossible, the host must record that failure
instead of pretending the finalizer succeeded.
The processor dispatches it after a terminal outcome, including provider
errors and worker cancellation (recorded as `interrupted`). A persisted
invocation ID prevents a completed finalizer from running twice for the same
task attempt and plugin; an incomplete invocation may be retried with that ID.
An Owner retry starts a new attempt and receives a new finalizer invocation.
Process death and forced termination cannot execute Python cleanup code, so
startup records an interrupted task for inspection. Delivery then requires a
manual retry; exactly-once external effects require plugin-side idempotency.

`pr.review` accepts a replacement only after Core checks its structured
result against the current PR head SHA. It does not grant the plugin direct
review submission or Owner Gate bypass. `waiting_for_plugin` is the common
top-level state for a plugin-requested pause; plugin-specific progress lives
in plugin data. Hooks do not create new Task kinds.

### Tools and Services

`register_tool` accepts a handler, a description, optional explicit input
schema, and `recommended_agents`. The SDK attempts to derive a JSON schema
from Python type hints when none is supplied. Core must validate the final
schema and arguments. Newly installed Tools are **not** enabled for an Agent
automatically; a recommendation requires an explicit owner action. Tools
return one text/JSON result in Preview 3. Cancellation is advisory first,
with a host watchdog as fallback.
Only `code_worker` can invoke plugin Tools in the current Agent runtime.
Recommendations and enablement for other Agents are unsupported in Preview 3.

`register_service` exposes an explicitly named plugin-to-plugin operation.
Its input/output schemas are optional for simple JSON-serializable services.
The consuming plugin declares a required or optional Maintune plugin
dependency in its manifest. Required missing dependencies prevent startup;
optional ones permit degraded startup. Core does not download missing
plugins. A long-lived public Service may declare an optional semantic
`version`; a consumer that supplies a `version` on `service.call` gets an
explicit mismatch error if the provider changed. Ordinary services can omit
this and rely on the providing plugin's version. This is a Service Registry,
not a general Event Bus.

### Model and Sandbox Providers

The SDK has registration methods for both provider kinds. A running Sandbox
provider may now be selected from the existing Sandbox settings and is used by
the real task path. Its handler receives one action at a time: `create`,
`read_file`, `write_file`, `exec`, or `destroy`. The plugin's normal encrypted
configuration supplies its connection settings. Core validates paths, limits,
and basic result shapes before forwarding data to the task. The selected
plugin must remain enabled; Core will not silently fall back to Local.

A Model provider registers a fixed list of public model IDs. Its `resolve`
handler returns `{ "base_url": "https://...", "api_key": "...", "model": "..." }`
for a selected ID. Core validates the endpoint, lists it alongside built-in
providers, and passes the resolved OpenAI-compatible endpoint into the
existing diagnostic, structured-Agent, and OpenHands code-worker paths. Its
connection settings are held in the plugin's encrypted config, not exposed in
the Provider API. A disabled plugin makes its model unavailable without
silently falling back. Preview 3 currently requires a plugin Model provider to
resolve to an OpenAI-compatible endpoint; arbitrary native provider protocols
are outside this contract. Built-in providers remain in Core.

## Configuration, data, and upgrade

The current v2 manifest accepts a constrained JSON Schema `config_schema`:
objects, arrays, strings, numbers, integers, booleans, enums, basic ranges,
defaults, and `secret` fields. Maintune is responsible for validation,
storage, encryption, and masked UI display. A plugin can use its dedicated
`data_dir` for its own JSON, SQLite, or other files; Core offers no separate
storage abstraction.
For Preview 3, `secret: true` is supported only on direct string properties
of the root config object. Nested secret declarations, secret defaults, and
secret enums are rejected when the package is installed.

A Provider's runtime `config_schema` describes the fields it uses from the
plugin's manifest `config_schema`. Core requires matching types and `secret`
flags, then validates the selected values before enabling the Provider. The
Plugins settings UI remains the single place to enter and mask those fields.

The target migration order is: plugin custom migration, Core reconciliation
with new defaults and removed fields, validation, then one atomic save.
Failure must preserve the old config and prevent the new plugin from starting.
The optional `on_upgrade(context, old_version, new_version)` concerns plugin-owned
data. A failure preserves its data for diagnosis; automatic rollback of the
entire data directory is outside Preview 3.

Package upgrades are intended to retain config and data while replacing
code and updating the isolated environment. Disable/reload stops new calls,
allows up to five seconds for active extension calls to finish, then stops
the process.
The in-process runtime cannot safely kill an arbitrary Python thread, so
reload there is best effort.

## UI, HTTP, and GitHub

Optional plugin UI belongs only under the dedicated Plugins area. It cannot
inject arbitrary components into Dashboard, Task, or PR pages. The declared
UI mode may be bundled resources or an iframe page. `register_route(name,
handler, methods=("GET",), access="authenticated")` exposes a static route
under `/api/plugins/<plugin-id>/...`; `access="external"` requires the plugin
to implement its own authentication. Access to the Core route namespace is
not part of the contract.

The current GitHub Core Client accepts `github.issue.get` and
`github.pull.get` with a `task_id`; these load the matching task's repository
and installation through Core. `github.comment` requires an active task with
an explicit Owner `implement` decision. `github.privileged.comment` bypasses
that ordinary decision gate for a trusted installed plugin. Both writes require
a stable `invocation_id`, use the controller's idempotent outbox, and record
an audit event without including the comment body. Neither level returns raw
credentials. More GitHub methods are not part of the v2 contract yet.

A third-party PR reviewer can register the experimental `pr.review` hook,
return `wait`, then later call `workflow.resume` with its original invocation
ID and a structured verdict for the current head SHA. Core rejects stale
heads and continues its existing Owner Gate and GitHub review flow. The
isolated-process compatibility test covers this without any private imports.

## MCP web review example

The [MCP web review example](../examples/plugins/mcp-review/README.md) packages
an external `pr.review` hook and a loopback Streamable HTTP gateway. It lets
an MCP client read captured tasks, prepare an immutable review and explicitly
resume the existing Controller flow. It does not receive GitHub credentials
or publish directly. Its test dependencies are isolated from Core.

The example README describes installation, authorization, persistence,
transport limits and the separate host fixes for large IPC messages and
uncertain GitHub writes. Public Webhook delivery and macOS hardware remain
unverified; the example does not imply those release gates are complete.

## Compatibility and release gate

An unchanged Preview 2 AstrBot Bridge `.mtp` release artifact is checked into
`tests/fixtures` as the v1 regression. Its exact SHA-256 is recorded in the
test. The regression exercises install, enable, actual child-process health
and status RPC, disable, and reload. This does not contact a production
AstrBot or QQ server. V1 remains Legacy with no removal date, and Core should
serve it through a compatibility path rather than require business-code
migration.

Preview 3 passed its release gates. The Stable preparation roadmap is tracked
in `.codex/v0.1.0-stable-goals.md`; Plugin API v2 remains a preview-stage API
until Stable compatibility gates and public developer artifacts are complete.

## Minimal reference example

Start with [the in-tree minimal example](../examples/plugins/example/README.md)
to read one observation Hook, one typed code_worker Tool, top-level secret
config and plugin-owned data_dir persistence. It is a developer reference,
not a production plugin. Use the [public template](https://github.com/mcxianyujun/maintune-plugin-template)
to start a project and [official AnySearch](https://github.com/mcxianyujun/maintune-plugin-anysearch)
for a real search integration. The advanced MCP Review example is a separate
roadmap phase; this reference does not demonstrate workflow replacement.
