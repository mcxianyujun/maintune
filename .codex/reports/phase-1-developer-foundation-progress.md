# v0.1.0 Stable Phase 1 — Developer Foundation progress

## Objective

Make the Plugin API v2 SDK and starter template usable outside Maintune Core, then publish the public developer foundation. Phase 1 is **not complete**: public GitHub repository creation was rejected by automatic approval review. The roadmap therefore remains at Phase 1; Phases 2–4 have not started.

## Changes made

- Added an exact [Plugin API reference](../../docs/plugin-api-reference.md) and [plugin development guide](../../docs/plugin-development.md). Updated the v2 guide to reflect that Preview 3 was actually released, while v2 remains preview-stage.
- Added SDK package metadata and explicit installation/security guidance. The SDK public Python surface and Core behavior were not changed.
- Made the in-tree starter template's tests independent of Core's source tree. README now gives a working local wheel route and does not claim that the proposed GitHub/PyPI packages are already published.
- Prepared two independent **local** Git repositories under the ignored `.tmp/stable-ecosystem/` directory: `maintune-plugin-sdk` and `maintune-plugin-template`. They have MIT licenses, `mcxianyujun` commit metadata, independent Git histories, package/test workflows and no Core-private imports. Neither repository was created on GitHub or pushed.
- The independent SDK repository uses a conventional `src/maintune_plugin_sdk` layout. This avoids pytest collecting a root-level `__init__.py` as a test package; the five public SDK Python files match the in-tree SDK byte-for-byte.

## Files/repositories changed

- Core branch `codex/v0.1.0-stable`: `sdk/maintune_plugin_sdk/{pyproject.toml,README.md}`, `docs/{plugin-api-v2.md,plugin-api-reference.md,plugin-development.md}`, `examples/plugins/template/{README.md,tests/test_template.py}`, this report and the roadmap.
- Local independent SDK repository: `.tmp/stable-ecosystem/maintune-plugin-sdk`, current local `main` commit `a7041bd`.
- Local independent template repository: `.tmp/stable-ecosystem/maintune-plugin-template`, current local `main` commit `73ba047`.

## Tests executed

- Core SDK/API/template targeted tests: **36 passed**.
- Independent SDK: wheel built in an ASCII-named clean temp directory, installed without dependencies in a fresh Python 3.12 venv, import/version check passed, **3 standalone tests passed**.
- Independent template: **2 standalone tests passed**, reproducible `.mtp` build passed, archive contains only the five allowlisted package files. Latest archive SHA-256: `94d4665978331a15d060359095bd1af6b4a8ec9a431ab390a6d5b6645a0ffb4f`.
- Core/independent SDK source parity: **five Python files matched**.
- Docs consistency: **9 document pairs passed**. Release audit: **PASS**, no high-confidence secret or forbidden release file; no product runtime behavior was changed.
- Narrow scan of both independent Git histories/file lists found no real server IP, SSH key material, GitHub token, admin token or production config.

## Known limitations and blocker

- `maintune-plugin-sdk` is not on PyPI; no PyPI publication was attempted.
- GitHub public repositories `mcxianyujun/maintune-plugin-sdk` and `mcxianyujun/maintune-plugin-template` do not exist yet. An attempted API request to create the first repository was **rejected before execution** by automatic approval review. The stated reason was that public repository creation with credentials is an irreversible publication side effect, the roadmap did not explicitly authorize doing it now, and `AGENTS.md` restricts unapproved real GitHub publication. No workaround or alternate route was used.
- The template's standalone CI references the proposed SDK repository. It must not be pushed until the SDK repository exists, or its dependency source is changed to an existing verified package.
- The local Python runtime mis-decoded the Chinese workspace path during an isolated package build. Building from an ASCII-named temporary copy succeeded; this is a developer-machine path issue, not an SDK API defect.

## Next phase readiness

**Not ready for Phase 2.** Phase 1 requires explicit authorization for creating the two named public GitHub repositories, then pushing the prepared histories and verifying their CI. The Stable roadmap forbids skipping ahead. No Stable tag, Release, production deployment, GHCR image or package-registry upload was performed.
