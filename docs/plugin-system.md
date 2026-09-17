# Maintune Plugin API v1

Plugin API v1 is Maintune's first public, out-of-process extension boundary. It
is Experimental during the Preview series, but its protocol is explicitly
versioned as `maintune.plugin.v1`.

## Package and installation

A Maintune Plugin Package uses the `.mtp` extension and is a ZIP-compatible
archive with this root layout:

```text
manifest.yaml
README.md
requirements.lock
src/<python package>/...
icon.webp                 # optional
```

The manifest declares identity, publisher, version, minimum Maintune version,
Plugin API version, entrypoint, capabilities, and typed configuration. Supported
configuration types are `string`, `boolean`, `integer`, `select`, `string_list`,
and `secret`. Secret values are encrypted with the Maintune Vault and are only
returned to the UI as `********`.

Copy packages to `data/plugins/inbox`. The Plugins page can scan, validate,
install, enable, disable, and uninstall them. Installed source is under
`data/plugins/installed`; private virtual environments, state, and the event
outbox are under `data/plugins/runtime`.

Validation happens before extraction or execution. Maintune rejects absolute or
parent paths, backslashes, symlinks, duplicate paths and plugin IDs, missing
entrypoints, oversized packages, incompatible versions, and invalid manifests.

## Runtime and IPC

Each enabled plugin runs in a separate Python virtual environment and process.
Maintune starts the entrypoint with isolated Python mode and a minimal operating
system environment. Provider, GitHub, SMTP, Sandbox, administrator, and other
application secrets are not inherited.

Core and plugin communicate through newline-delimited JSON-RPC 2.0 on standard
input/output. This works on Linux and Windows without Unix sockets. Messages are
limited to 1 MiB. Core enforces startup and request timeouts, health checks,
crash detection, bounded sanitized stderr, and lifecycle shutdown. A plugin
crash changes only that plugin's status.

Plugins request Core operations with `capability.call`. Core checks each request
against the manifest before dispatch. v1 capabilities are `repository.read`,
`task.read`, `event.subscribe`, `owner_decision.submit`, `plugin.log`, and
`plugin.health`.

There is no database, Controller object, GitHub client, shell, Provider, prompt,
or arbitrary route capability. Owner decisions accept only `implement`,
`reject`, and `defer`, require a replay key, and re-enter the existing Controller
and Policy path.

## HTTP and WebSocket namespace

External transports use Maintune's existing HTTPS listener under
`/api/plugins/{plugin_id}/...`. Plugin code cannot register root, `/api`,
`/admin`, or `/webhooks` routes. The AstrBot bridge uses
`/api/plugins/official.astrbot-bridge/ws`; Core authenticates the dedicated
Bridge Token, applies message limits, and relays bounded messages to the plugin
process. No additional public port or firewall rule is required.

## Event model and reliability

Events use this shape:

```json
{
  "protocol": "maintune.plugin.v1",
  "event": "task.waiting_for_owner",
  "event_id": "evt_0123456789abcdef0123456789abcdef",
  "timestamp": "2026-09-18T00:00:00+00:00",
  "repository": "example/repository",
  "task": {"id": "42", "status": "waiting_for_owner", "title": "Example"},
  "data": {"reason": "Owner policy decision required"}
}
```

The event serializer removes fields whose names indicate prompts, tokens,
credentials, private keys, passwords, or secrets. Hidden reasoning is never an
event field. Critical events are retained in a bounded per-plugin outbox until
the remote peer acknowledges their `event_id`. Consumers must persist event IDs
and deduplicate because delivery is at least once.

## AstrBot bridge

The first official external plugin is `official.astrbot-bridge`. Its dedicated
token grants only event read, task read, and Owner Decision submission. Token
regeneration invalidates the old token. The reverse AstrBot connection uses the
separate `maintune.astrbot.v1` protocol documented in the plugin repository.
