"""Private planning material must never enter source release bundles."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_source_bundle_excludes_tracked_private_material(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("release_builder", ROOT / "scripts/build_release.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    paths = ["README.md", ".codex/reports/private.md", ".tmp/state.txt", ".env", "data/private.db"]
    for name in paths:
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("private" if name != "README.md" else "public")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module.subprocess, "check_output", lambda *a, **kw: b"\0".join(n.encode() for n in paths) + b"\0")
    assert module.candidates() == [Path("README.md")]


def test_source_archives_do_not_depend_on_checkout_mtimes(tmp_path, monkeypatch):
    import os
    spec = importlib.util.spec_from_file_location("release_builder", ROOT / "scripts/build_release.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    (tmp_path / "frontend/dist").mkdir(parents=True)
    (tmp_path / "frontend/dist/index.html").write_text("<html>release</html>")
    (tmp_path / "README.md").write_text("public source")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "OUT", tmp_path / "release-dist")
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1700000000")
    monkeypatch.setattr(module.subprocess, "check_output", lambda *a, **kw: b"README.md\0")
    module.main()
    first = {p.name: p.read_bytes() for p in module.OUT.iterdir()}
    os.utime(tmp_path / "README.md", (1800000000, 1800000000))
    module.main()
    assert first == {p.name: p.read_bytes() for p in module.OUT.iterdir()}
