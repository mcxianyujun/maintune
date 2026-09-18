"""Fail when bilingual deployment docs drift on stable operational tokens."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAIRS = ["linux", "windows", "docker-compose", "setup-wizard", "github-app", "sandbox", "upgrade", "backup-restore", "troubleshooting"]
STABLE_TOKENS = {
    "linux": ["0.1.0-preview.2", "scripts/linux/install.sh", "Shipyard Neo", "Setup Wizard"],
    "windows": ["0.1.0-preview.2", "install.ps1", "docker compose", "Setup Wizard"],
    "docker-compose": ["MAINTAINER_ADMIN_TOKEN", "MAINTAINER_ENCRYPTION_KEY", "MAINTAINER_BIND_ADDRESS", "MAINTAINER_PORT", "MAINTAINER_DATA_DIR", "docker compose"],
    "setup-wizard": ["Setup Wizard", "Shipyard Neo"],
    "github-app": ["/webhooks/github", "https://api.github.com"],
    "sandbox": ["Shipyard Neo"],
    "upgrade": [], "backup-restore": [], "troubleshooting": ["Shipyard"],
}

errors: list[str] = []
for name in PAIRS:
    english = (ROOT / "docs" / "en" / f"{name}.md").read_text(encoding="utf-8")
    chinese = (ROOT / "docs" / "zh-CN" / f"{name}.md").read_text(encoding="utf-8")
    for token in STABLE_TOKENS[name]:
        if token not in english or token not in chinese:
            errors.append(f"{name}: stable token missing from a locale: {token}")
if errors:
    raise SystemExit("\n".join(errors))
print(f"Bilingual docs consistency passed for {len(PAIRS)} document pairs")
