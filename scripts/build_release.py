"""Create source-only Preview bundles and checksums.

The bundle intentionally contains no dependency artifact or runtime image.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
META = json.loads((ROOT / "release.json").read_text(encoding="utf-8"))
VERSION = META["version"]
PREFIX = f"maintune-v{VERSION}"
OUT = ROOT / "release-dist"

EXCLUDED_PARTS = {".git", ".venv", ".pnpm-store", ".codex-remote-attachments", "node_modules", "data", "backups", "test-results", "release-dist", "__pycache__"}
EXCLUDED_NAMES = {".env"}
EXCLUDED_SUFFIXES = {".whl", ".sqlite", ".sqlite3", ".db", ".log", ".pem", ".key", ".p12", ".pfx", ".pyc"}


def candidates() -> list[Path]:
    output = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=ROOT
    )
    result = []
    for raw in output.split(b"\0"):
        if not raw:
            continue
        relative = Path(os.fsdecode(raw))
        if any(part in EXCLUDED_PARTS for part in relative.parts) or relative.name in EXCLUDED_NAMES or relative.suffix.lower() in EXCLUDED_SUFFIXES:
            continue
        source = ROOT / relative
        if source.is_file():
            result.append(relative)
    for source in (ROOT / "frontend" / "dist").rglob("*"):
        if source.is_file():
            relative = source.relative_to(ROOT)
            if relative not in result:
                result.append(relative)
    return sorted(result, key=lambda item: item.as_posix())


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    if not (ROOT / "frontend" / "dist" / "index.html").is_file():
        raise SystemExit("Build frontend/dist before creating a release bundle")
    files = candidates()
    forbidden = [item for item in files if item.suffix.lower() in EXCLUDED_SUFFIXES or item.name == ".env"]
    if forbidden:
        raise SystemExit("Forbidden release content: " + ", ".join(map(str, forbidden)))
    OUT.mkdir(exist_ok=True)
    for old in OUT.glob(f"{PREFIX}.*"):
        old.unlink()
    with tempfile.TemporaryDirectory(prefix="ai-maintainer-release-") as temporary:
        bundle = Path(temporary) / PREFIX
        for relative in files:
            destination = bundle / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, destination)
        tar_path = OUT / f"{PREFIX}.tar.gz"
        with tarfile.open(tar_path, "w:gz", format=tarfile.PAX_FORMAT) as archive:
            for path in sorted(bundle.rglob("*")):
                arcname = Path(PREFIX) / path.relative_to(bundle)
                info = archive.gettarinfo(str(path), str(arcname))
                info.uid = info.gid = 0
                info.uname = info.gname = "root"
                if path.suffix == ".sh":
                    info.mode |= stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
                if path.is_file():
                    with path.open("rb") as stream:
                        archive.addfile(info, stream)
                else:
                    archive.addfile(info)
        zip_path = OUT / f"{PREFIX}.zip"
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in sorted(bundle.rglob("*")):
                if path.is_file():
                    archive.write(path, (Path(PREFIX) / path.relative_to(bundle)).as_posix())
    checksum_path = OUT / "SHA256SUMS"
    with checksum_path.open("w", encoding="ascii", newline="\n") as stream:
        stream.write("".join(f"{sha256(path)}  {path.name}\n" for path in (tar_path, zip_path)))
    print(f"release-bundle: files={len(files)}")
    print(f"release-bundle: {tar_path.name} {tar_path.stat().st_size} bytes")
    print(f"release-bundle: {zip_path.name} {zip_path.stat().st_size} bytes")
    print("release-bundle: PASS (source only; no wheel, cache, secret, database, log or backup)")


if __name__ == "__main__":
    main()
