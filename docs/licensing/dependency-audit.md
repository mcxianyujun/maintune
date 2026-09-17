# Dependency license audit

Audit date: 2026-09-16  
Target: `v0.1.0-preview.1` release candidate

## Result

**Source/local-build distribution accepted; public prebuilt container redistribution remains disabled.**

The direct application dependencies and the installed frontend dependency tree use common open-source licenses (MIT, Apache-2.0, BSD, ISC, MPL-2.0 and CC-BY-4.0). One transitive Python dependency is explicitly marked proprietary:

```text
openhands-sdk 1.47.0
└── lmnr 0.7.62
    └── lmnr-claude-code-proxy 0.1.24  (LicenseRef-Proprietary)
```

`lmnr-claude-code-proxy` ships inside the locked Python environment and therefore would be redistributed in a public GHCR image. The package metadata provides no redistribution grant, and its referenced source repository is not public. Preview therefore does not publish a prebuilt image. The Release Bundle contains no wheel, sdist, source copy, cache, or container image; the user-local Docker build obtains the pinned dependency from its official package source.

Public prebuilt images remain blocked until one of the following is documented and verified:

1. the rights holder provides terms that allow redistribution in the public container image;
2. OpenHands provides a supported dependency configuration that omits the package while preserving the tested runtime; or
3. the runtime dependency is replaced through a separately reviewed architecture change.

This report records metadata and compatibility risk; it is not legal advice.

## Evidence

- Python lock: 142 pinned distributions inspected from `requirements.lock`; the final image report contains 146 installed distributions including Maintune and build/runtime support packages.
- Frontend lock: all installed packages inspected with pnpm's license report.
- OpenHands SDK repository declares MIT, but its SDK requirement includes `lmnr`, whose requirement includes the proprietary package above.
- Metadata without an explicit license was also observed for `agent-client-protocol`, `openhands-sdk`, and `socksio`; OpenHands was cross-checked against its official MIT repository. The remaining metadata gaps should be resolved in the final NOTICE/SBOM before release.

## Minimal-install investigation

The Maintainer runtime uses `Action`, `Agent`, `LLM`, `LocalConversation`, custom tools and the event model from `openhands-sdk`. An import probe that rejected every `lmnr` and `lmnr-claude-code-proxy` import successfully loaded this full API surface; neither package entered `sys.modules`. Inspection of OpenHands shows that `lmnr` is imported lazily by its Laminar observability integration. Maintainer does not enable Laminar, so the proprietary proxy is not part of the active agent loop.

This does not provide a compliant packaging solution:

- OpenHands SDK 1.47.0 declares `lmnr>=0.7.60,<0.8.0` as a mandatory dependency, rather than an optional extra.
- OpenHands SDK 1.48.0 and the current upstream source retain the same mandatory dependency.
- `lmnr` 0.7.56 already declared `lmnr-claude-code-proxy>=0.1.22`, so selecting the earliest version accepted by nearby OpenHands releases does not avoid the package.
- In an isolated metadata environment containing the complete installed dependency set except `lmnr-claude-code-proxy`, `pip check` failed with: `lmnr 0.7.62 requires lmnr-claude-code-proxy, which is not installed.`

No supported minimal install, telemetry extra, or OpenHands subpackage was found that supplies the Maintainer API surface without this dependency. Removing it with `--no-deps` cannot meet the required `pip check` acceptance criterion. Making `pip check` pass would require patching upstream wheel metadata, creating a fake `lmnr` compatibility distribution, vendoring selected SDK modules, or changing to a remote Agent Server architecture. The first three are effectively upstream forks or unsupported package substitutions; the last is a core runtime/deployment architecture change. None was implemented.

## Scope and next check

Repeat this audit from the exact locally built release container and retain the dependency report with release-candidate evidence. A source Release Bundle and a prebuilt image have different redistribution surfaces. This blocker applies to a public prebuilt image, which is **not provided in v0.1.0-preview.1**; it no longer blocks the source/local-build Preview. Restoring GHCR distribution requires an upstream packaging change or explicit redistribution permission.
