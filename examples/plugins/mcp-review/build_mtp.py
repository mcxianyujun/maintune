# SPDX-License-Identifier: MIT
"""Build deterministic archives from an explicit allowlist, never local data."""

import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PLUGIN = ["manifest.yaml", "src/web_review.py", "README.md", "LICENSE"]
GATEWAY = ["gateway.py", "setup_gateway.py", "locales/zh-CN.json", "Start Gateway.cmd", "Start Gateway.command", "README.md", "LICENSE"]


def archive(path, files):
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name, content in sorted(files.items()):
            info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (0o100755 if name.endswith(".command") else 0o100644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            bundle.writestr(info, content)


def build():
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    version = json.loads((ROOT / "manifest.yaml").read_text(encoding="utf-8"))["version"]
    plugin = dist / f"maintune-web-review-{version}.mtp"
    archive(plugin, {name: (ROOT / name).read_bytes() for name in PLUGIN})
    bundle = dist / f"maintune-web-review-{version}-bundle.zip"
    archive(bundle, {plugin.name: plugin.read_bytes(), **{name: (ROOT / name).read_bytes() for name in GATEWAY}})
    (dist / "SHA256SUMS").write_text("".join(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n" for path in (plugin, bundle)), encoding="ascii", newline="\n")
    return plugin


if __name__ == "__main__":
    print(build())
