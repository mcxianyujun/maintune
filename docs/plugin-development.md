# Develop a Maintune Plugin API v2 plugin

This is the shortest supported path from a new Python project to an installable `.mtp` package. Start with [`examples/plugins/template`](../examples/plugins/template); it imports only the public MIT-licensed `maintune_plugin_sdk`. The [API reference](plugin-api-reference.md) lists the exact registrations and Core calls. Plugin API v1 packages remain supported through the Legacy path.

## Prerequisites

- Python 3.12 or later for development and the isolated plugin runtime.
- A Maintune instance with Plugin API v2 (`v0.1.0-preview.3` or newer).
- A compatible SDK. Build a wheel from `sdk/maintune_plugin_sdk` with `python -m pip wheel --no-deps --wheel-dir dist .` and install it in a clean development environment. The separate Git repository and PyPI package must not be assumed available until their publication is verified.

Do not import `maintainer.*`, open Maintune's database, or copy host credentials into your plugin. A plugin installed by an administrator is trusted code, but Core still owns GitHub policy and secret storage.

## Create and validate

1. Copy the template to a standalone directory. Change `id`, `name`, `publisher`, version and description in `manifest.yaml`; use a publisher identifier you control. Keep `plugin_api: 2` and an isolated runtime.
2. Implement `register(api)` in the module named by `entrypoint.python`. Register only the Hook, Tool, Service, Provider or route your plugin actually implements. A Tool recommendation is metadata; an administrator must enable it, and only `code_worker` can invoke plugin Tools in this version.
3. Declare user-editable settings in `config_schema`. Place sensitive values in direct root string fields marked `secret: true`. Nested secret declarations are rejected. Never print decrypted values or include them in a Tool result.
4. Document installation, configuration, permissions, external services and failure behavior in the package's `README.md`. Declare Python dependencies in `requirements.txt`; avoid installation scripts.
5. Run `python -m unittest discover -s tests -v` with the SDK installed. Build `python build_mtp.py`, then inspect the resulting ZIP member list before installing it. The template builder includes an explicit file allowlist and reproducible timestamps.
6. Install the `.mtp` through Maintune's plugin page or inbox on a test instance. Confirm process health, registration, expected invocation, masked secret display, disable/reload and error behavior. Test against an untrusted input where your plugin reads external data.

The plugin archive is a ZIP payload but should be distributed as `.mtp`. Maintune validates paths, symlinks, package size, API compatibility and entrypoint before extraction. Installation does not enable a Tool for an Agent automatically.

## Extension selection

| Need | Public mechanism | Important limit |
| --- | --- | --- |
| Observe task lifecycle | `task.started`, `task.finally` Hooks | Use `invocation_id` for idempotency; forced process death cannot run finalizer Python. |
| Let `code_worker` request a result | Agent Tool | Single text/JSON result; no streaming or arbitrary Agent injection. |
| Share a bounded operation with another plugin | Plugin Service | Consumer declares a plugin dependency. |
| Supply an OpenAI-compatible model endpoint | Model Provider | Built-in Provider secrets are not exposed; plugin config carries its own secret. |
| Supply a Sandbox implementation | Sandbox Provider | Selection is explicit; no silent fallback to Local. |
| Expose a plugin-owned HTTP endpoint | Namespaced route | Cannot occupy Core's `/api/*` namespace; external access needs plugin authentication. |
| Pause and resume PR review | Experimental `pr.review` Hook | Return `wait`, then `workflow.resume` with current head SHA; Core retains Owner Gate and GitHub writes. |

## Release checklist

- Build/test from a clean checkout with a pinned compatible SDK version.
- Keep package metadata, README, LICENSE and changelog consistent. Record the `.mtp` SHA-256.
- Verify no API keys, local config, SSH keys, database, logs, caches or production endpoint values are in the archive or Git history.
- Test against the released Maintune version you claim to support, including enable/disable and upgrade if you maintain state.
- State unverified integrations explicitly. A mocked API call is not evidence of a real external service E2E.

Plugin API v2 is still preview-stage in `v0.1.0-preview.3`. No marketplace, signing, Event Bus, Custom Task, ReviewProvider abstraction, Tool streaming, remote runtime or automatic plugin code rollback is promised.
