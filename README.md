# Maintune

A self-hosted autonomous maintainer for GitHub.

Maintune is currently in Preview.

[English](README.md) | [简体中文](README.zh-CN.md)

A self-hosted GitHub repository maintenance console. **v0.1.0-preview.1** receives Issue and Pull Request events through a GitHub App, asks bounded Agents for analysis or code review, and leaves every GitHub write to the Controller and deterministic Policy.

The default interface uses a light Luo Tianyi-inspired palette centered on `#66CCFF`, with project-generated fan artwork and chibi navigation icons. No official or unverified third-party artwork is included. See [Artwork and attribution](docs/licensing/asset-attribution.md) for the exact rights boundary.

![Maintune preview](docs/images/preview-dashboard.png)

## Preview status

- Issue triage separates actionable bugs, incomplete reports, product features, high-risk changes, and non-actionable chat.
- Actionable Issue → Sandbox fix → tests → independent review → PR.
- External PR review, synchronize re-review, technical change requests, and deterministic owner gates for product or sensitive changes.
- OpenAI-compatible models, OpenHands SDK Runtime, and Local or Shipyard Neo Sandbox.
- Bilingual `zh-CN` / `en-US` WebUI, Setup Wizard, evidence timeline, usage, diagnostics, and backup workflows.
- Windows 11, Ubuntu 24.04, and Docker Compose local-build deployment paths.

This Preview is intended for maintainers and small teams who can self-host and review automation policy. It does not promise unattended operation, universal automatic fixes, or a stable plugin API.

## Quick start

### Windows 11

Requires Windows 11, Docker Desktop with the WSL2 backend, and Docker Compose v2. Download and verify the release bundle, then run:

```powershell
.\scripts\windows\install.ps1
```

### Linux

Requires Docker Engine, Docker Compose v2, `curl`, `tar`, and `sha256sum`:

```bash
chmod +x scripts/linux/*.sh
./scripts/linux/install.sh
```

### Docker Compose

```bash
cp .env.example .env
# Set random administrator-token and encryption-key values.
docker compose build --pull
docker compose run --rm --no-deps maintainer pip check
docker compose up -d --wait
```

Open `http://127.0.0.1:8000` and complete the Setup Wizard. Put an HTTPS reverse proxy in front of any public deployment.

## Feature status and known limitations

| Component | Preview status |
| --- | --- |
| Windows 11 installer | Available; final Docker Desktop E2E remains a manual verification item |
| Linux installer | Available; Ubuntu 24.04 is the acceptance target |
| Docker Compose | Available; images are built locally |
| Prebuilt GHCR image | **Not provided in v0.1.0-preview.1** |
| Plugin system | **Experimental**; interfaces may change |

The installer builds on the user's machine and downloads pinned dependencies from their official package sources. Preview requires network access to GitHub, PyPI, and the configured base-image registry and does not provide a fully offline installation path.

## Security boundary

Local Sandbox limits paths, working directories, timeouts, and environment variables; it is not a strong isolation boundary. Use Shipyard Neo for untrusted repositories. Models and repository content are untrusted. Sandbox processes never receive Controller credentials, and Agents never directly authorize GitHub writes.

## Documentation

- [Linux](docs/en/linux.md) · [中文](docs/zh-CN/linux.md)
- [Windows 11](docs/en/windows.md) · [中文](docs/zh-CN/windows.md)
- [Docker Compose](docs/en/docker-compose.md) · [中文](docs/zh-CN/docker-compose.md)
- [Setup Wizard](docs/en/setup-wizard.md) · [中文](docs/zh-CN/setup-wizard.md)
- [GitHub App](docs/en/github-app.md) · [中文](docs/zh-CN/github-app.md)
- [Sandbox](docs/en/sandbox.md) · [中文](docs/zh-CN/sandbox.md)
- [Upgrade](docs/en/upgrade.md) · [中文](docs/zh-CN/upgrade.md)
- [Backup and restore](docs/en/backup-restore.md) · [中文](docs/zh-CN/backup-restore.md)
- [Troubleshooting](docs/en/troubleshooting.md) · [中文](docs/zh-CN/troubleshooting.md)
- [Preview release notes](docs/preview-release.md)
- [Artwork and attribution](docs/licensing/asset-attribution.md)

## Licensing

Maintune uses a dual-license model:

- **AGPL-3.0-only** — commercial use is allowed for users who comply with the AGPL terms, including its source-availability obligations where they apply.
- **Commercial License** — available by separate written agreement with **mcxianyujun** for proprietary, closed-source, OEM, or other alternative licensing needs.

Project-authored or project-generated Luo Tianyi derivative visuals use [CC BY-NC-SA 4.0](LICENSES/CC-BY-NC-SA-4.0.txt), only within rights owned or controlled by the project author. Luo Tianyi / VSINGER names, character settings, original character design, likeness, trademarks, and underlying IP are outside the project's AGPL and CC grants and remain with their rights holders. The visuals are fan-made and are not official VSINGER artwork.

Third-party dependencies retain their own licenses. See [NOTICE](NOTICE), [COMMERCIAL-LICENSE.md](COMMERCIAL-LICENSE.md), and [CONTRIBUTING.md](CONTRIBUTING.md).
