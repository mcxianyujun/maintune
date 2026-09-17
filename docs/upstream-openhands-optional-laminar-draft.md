# Draft: Make Laminar observability dependency optional

## Problem

Downstream SDK consumers that use the OpenHands conversation/agent/tool APIs without Laminar observability still receive `lmnr` as a mandatory dependency. `lmnr` currently introduces an unrelated Claude Code proxy package into otherwise minimal Runtime images.

## Evidence

Our adapter uses the SDK Agent, Conversation, LLM and tool bridge. Read, write, shell, tests and the Agent loop work without importing Laminar paths, but removing `lmnr` makes `pip check` fail because packaging declares it mandatory.

## Request

Could the SDK move Laminar integration to an optional extra, for example `openhands-sdk[laminar]`, while keeping core SDK imports and execution functional without it? This would reduce dependency surface for downstream Runtime consumers that provide their own observability.

This is a draft only. Do not post it without project-owner authorization.
