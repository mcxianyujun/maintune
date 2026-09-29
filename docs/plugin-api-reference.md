# Maintune Plugin API v2 — Python reference

This describes the public `maintune_plugin_sdk` 2.0.0 package shipped with Maintune `v0.1.0-preview.3`. The SDK is MIT-licensed and imports no Maintune Core modules. The host-side contract, validation and permissions are implemented by Core; installing the SDK alone does not grant any capability. Plugin API v1 remains available through the Legacy path.

## Entrypoint and context

An `.mtp` package declares `plugin_api: 2` and a Python entrypoint module. That module exports `register(api: PluginAPI)`. The host calls it after starting the plugin's isolated Python process. The supported transport is UTF-8 newline-delimited JSON-RPC 2.0 over stdio (`maintune.plugin.v2`, maximum 1 MiB per message). Standard output is reserved for protocol traffic; ordinary `print` and logging go to sanitized standard error.

`PluginContext` provides `plugin_id`, `plugin_version`, `data_dir`, `config`, `invocation_id`, `logger`, `cancelled`, `wait_cancelled()`, and `async call_core(method, params={})`. `config` may contain decrypted plugin-specific secrets at runtime; never print or return it. The context does not provide a database session, Controller object, GitHub credentials, or task/Agent IDs. Hooks carry task identifiers in their validated payloads where applicable. Cancellation is advisory; a forcibly terminated process cannot run Python cleanup handlers.

Handlers may be synchronous or asynchronous. A first parameter named `context` or `ctx` receives `PluginContext`. For Tools, the remaining parameters receive named model-supplied arguments. Other extension handlers receive one JSON object payload.

## Registration methods

| Method | Contract |
| --- | --- |
| `register_hook(name, handler, priority=100)` | Registers a catalog Hook. Priority must be between -1000 and 1000. |
| `on_task_finally(handler)` | Registers the `task.finally` lifecycle Hook. Use `context.invocation_id` to make external effects idempotent. |
| `register_tool(name, handler, *, description, input_schema=None, recommended_agents=())` | Registers a namespaced Agent Tool. Core validates arguments and result; only `code_worker` can invoke plugin Tools in this release. Recommendations never enable a Tool automatically. |
| `register_service(name, handler, *, description="", input_schema=None, output_schema=None, version=None)` | Registers an explicitly named plugin-to-plugin Service. Consumers declare the provider as a manifest dependency. |
| `register_model_provider(name, handler, *, config_schema, models)` | Resolves listed model IDs to an OpenAI-compatible endpoint. Plugin config remains encrypted/masked by Core. |
| `register_sandbox_provider(name, handler, *, config_schema)` | Handles the selected Sandbox provider's `create`, `read_file`, `write_file`, `exec`, and `destroy` actions. |
| `register_route(name, handler, *, methods=("GET",), access="authenticated")` | Exposes a static method/path in the plugin's own `/api/plugins/<plugin-id>/...` namespace. `external` access requires plugin-owned authentication. |

Extension names use lowercase ASCII letters, digits, underscore, period and hyphen, start with a letter, and have at most 64 characters. Core publishes IDs as `<plugin-id>/<name>`. Duplicate registrations are rejected. Registration metadata is public; keep credentials in encrypted plugin config instead of registration arguments.

When `input_schema` is omitted for a Tool, the SDK derives a small JSON Schema from annotated parameters: `str`, `int`, `float`, `bool`, `Literal[...]`, `list[T]`, string-keyed dictionaries, and optional parameters with a default. Complex unions or custom objects require an explicit object schema. Unsupported annotations fail registration rather than silently broadening input.

## Hook catalog

| Hook | Stability | Input/result behavior |
| --- | --- | --- |
| `task.started` | Stable | Notification; parallel and fail open. |
| `task.finally` | Stable | Terminal task notification with `task_id`, `status`, `attempt`, and optional `summary`; serial and fail open. A completed invocation is not rerun for the same task attempt and plugin. Incomplete delivery may retry the same invocation ID. Forced plugin/process termination prevents Python cleanup; the host records the interruption. |
| `issue.analysis_prompt` | Experimental | Pipeline; may continue, modify a validated prompt payload, or cancel. Serial and fail open. |
| `pr.review` | Experimental | Replaceable structured review; may continue, replace, cancel, or wait. Core validates a replacement against the current PR head and retains its Owner Gate and GitHub write policy. |

`pr.review` replacement results contain `head_sha`, `verdict` (`approved`, `changes_required`, or `owner_decision`), `summary`, `risk`, `blocking_issues`, and `suggestions`. A waiting plugin later calls `workflow.resume` with the original invocation ID and result. Stale head SHA, duplicate resume, or a task that is no longer waiting is rejected. No general Event Bus, ReviewProvider interface, or Custom Task type is part of this API.

## Documented `context.call_core` methods

| Method | Purpose and boundary |
| --- | --- |
| `task.status`, `task.list`, `task.get` | Read task state using the `task.read` capability. |
| `repository.list`, `repository.get` | Read repository metadata using `repository.read`. |
| `owner_decision.submit` | Submit an explicit structured decision through the existing Controller path; it does not bypass the Owner Gate. |
| `plugin.log` | Write a sanitized plugin log entry. |
| `service.call` | Invoke a registered Service. The caller must declare the provider as a plugin dependency; an optional requested version is checked. |
| `workflow.resume` | Resume a task waiting on this plugin's `pr.review` invocation with a structured result for the current head SHA. |
| `github.issue.get`, `github.pull.get` | Read the current task's Issue/PR through Core's GitHub App installation. |
| `github.comment` | Request an idempotent comment on an active, owner-approved task. Requires stable `invocation_id`; Controller performs the write and audit. |
| `github.privileged.comment` | Explicit privileged comment path for a trusted installed plugin. Still goes through Controller and audit and requires stable `invocation_id`. Grant only when the trust decision warrants it. |

Unknown methods are rejected. Plugins never receive GitHub installation tokens or raw App private keys. The normal GitHub write path requires an active task with an Owner `implement` decision. A plugin cannot directly approve, merge or otherwise bypass deterministic policy.

## Package and configuration boundaries

The `.mtp` ZIP includes `manifest.yaml` and `src/`; optional `README.md`, dependency file and plugin UI assets are validated before extraction. The package validator rejects traversal, symlinks, oversized archives, invalid manifests and unsupported API versions. See [developer guide](plugin-api-v2.md) for the manifest and [plugin system](plugin-system.md) for the v1 compatibility path.

The v2 `config_schema` supports a constrained JSON Schema subset. `secret: true` is supported only on direct string properties of the root config object; nested secrets, secret defaults and secret enums are rejected. Core encrypts accepted secret values at rest and masks them in browser APIs. Plugins should not return secrets in Tool, Service, Hook, Provider or route results.

Isolated plugin processes are separate from Core, but installed plugins are administrator-selected trusted code. In-process mode is advanced and cannot safely kill arbitrary Python threads. Plugin signing, marketplace trust, remote transport, streaming Tool results and automatic code rollback are not provided.
