# SPDX-License-Identifier: MIT
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = Path(os.environ.get("MAINTUNE_SOURCE", ROOT.parents[2]))
if not (UPSTREAM / "sdk" / "maintune_plugin_sdk").is_dir():
    raise RuntimeError("Set MAINTUNE_SOURCE to a Maintune Plugin API v2 checkout")
sys.path[:0] = [str(ROOT), str(ROOT / "src"), str(UPSTREAM / "sdk"), str(UPSTREAM / "backend")]
