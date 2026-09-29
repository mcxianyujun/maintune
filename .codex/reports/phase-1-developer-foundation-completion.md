# v0.1.0 Stable Phase 1 — Developer Foundation completion

## Objective

Provide a usable public Plugin API v2 SDK, a standalone starter template, an API reference and a developer guide, without changing Core's runtime contract or starting later roadmap phases. Phase 1 is **COMPLETE**. This report supersedes the historical blocked status recorded in `phase-1-developer-foundation-progress.md` after the owner explicitly authorized publication of the two named public repositories.

## Changes made

- Published [maintune-plugin-sdk](https://github.com/mcxianyujun/maintune-plugin-sdk) as a standalone MIT-licensed Python 3.12 package. It uses a conventional `src/maintune_plugin_sdk` layout, contains the same five public SDK Python files as the in-tree package, and has independent tests and GitHub Actions for install, pytest, wheel and `pip check`.
- Published [maintune-plugin-template](https://github.com/mcxianyujun/maintune-plugin-template) as a standalone MIT-licensed starter. It depends only on the public SDK, includes a minimal Tool, a reproducible `.mtp` builder, offline tests and GitHub Actions. The template CI installs the SDK from its public Git repository.
- Added [Plugin API reference](../../docs/plugin-api-reference.md) and [plugin development guide](../../docs/plugin-development.md) to Maintune Core. Updated the v2 guide's Preview 3 release status and the in-tree SDK/template installation instructions. No Plugin API behavior or runtime architecture changed.
- Kept package metadata under the public name `mcxianyujun`. No real person name, production credential or machine-specific endpoint was added to the public repositories.

## Repositories, contents and final commits

| Repository | Public `main` commit | Pushed contents |
| --- | --- | --- |
| [mcxianyujun/maintune-plugin-sdk](https://github.com/mcxianyujun/maintune-plugin-sdk) | `8fa78b212ea47d89bdd39b35ca6bac9fefe2b147` | MIT LICENSE, README, `pyproject.toml`, public SDK source, standalone tests, SDK CI. |
| [mcxianyujun/maintune-plugin-template](https://github.com/mcxianyujun/maintune-plugin-template) | `9a54728f239986193d7baaca958039e299b0f62d` | MIT LICENSE, bilingual README, manifest, reproducible `.mtp` builder, minimal source, tests, Template CI. |

The public GitHub API confirmed both repositories have `visibility=public` and their `main` branches point to the SHAs above. The local source audit found no embedded server IP, SSH key, GitHub token, Maintune admin token or production configuration. Core changes are isolated on `codex/v0.1.0-stable`; Preview 1/2/3 tags and releases remain unchanged.

## Tests executed

- Maintune targeted SDK/API/template tests: **36 passed**. Phase 0 baseline plugin suite: **55 passed**.
- Standalone SDK: wheel built from an isolated clean path, installed in a fresh Python 3.12 environment, import/version check passed, **3 tests passed**, and the five SDK Python files matched the in-tree source byte-for-byte.
- Standalone template: **2 tests passed**; `.mtp` builder produced the five allowlisted members.
- GitHub [SDK CI run 36537502045](https://github.com/mcxianyujun/maintune-plugin-sdk/actions/runs/36537502045): **SUCCESS** (install, tests, wheel, `pip check`).
- GitHub [Template CI run 36537539992](https://github.com/mcxianyujun/maintune-plugin-template/actions/runs/36537539992): **SUCCESS** (public SDK install, tests, `.mtp` build, archive check).
- Bilingual deployment documentation consistency: **9 document pairs passed**. Maintune release audit: **PASS** with no high-confidence secret or forbidden release file.

## Known limitations

- The SDK is public as a Git repository and wheel-buildable source; **it is not published to PyPI**. Documentation gives a working Git installation path and a local wheel option.
- Plugin API v2 remains a preview contract until the later Stable RC gate. `pr.review` and some Hooks remain experimental; Agent Tools are available to `code_worker` only.
- The template demonstrates packaging and a simple Tool; it is not a marketplace, signing system or endorsement of arbitrary plugin code.
- The local Python environment mis-decoded the Chinese workspace path during one build attempt. An ASCII-named clean temporary build succeeded; Ubuntu GitHub Actions also passed.

## Next-phase readiness and stop boundary

Phase 1 deliverables are complete and verified. Phase 2 (Official AnySearch Plugin) remains **TODO** and was **not started** because the owner explicitly limited this authorization to Phase 1 publication. No Stable tag, Maintune Core Release, PyPI publication, GHCR image or production deployment was performed.
