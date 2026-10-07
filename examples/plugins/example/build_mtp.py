"""Create a reproducible .mtp archive without plugin install scripts."""

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
MEMBERS = (
    "manifest.yaml", "README.md", "requirements.txt",
    "src/workflow_notes.py", "LICENSE",
)


def build(output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as package:
        for name in MEMBERS:
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            package.writestr(info, (ROOT / name).read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build the minimal Plugin API v2 example .mtp package")
    parser.add_argument("output", type=Path, nargs="?", default=ROOT / "dist" / "workflow-notes-example.mtp")
    build(parser.parse_args().output)
