# SPDX-License-Identifier: MIT
import hashlib
import json
import subprocess
import sys
import zipfile
import pytest

from build_mtp import ROOT, build
from gateway import validate_config
from setup_gateway import repository


def test_package_reproducible_and_no_private_files():
    plugin = build()
    first = hashlib.sha256(plugin.read_bytes()).hexdigest()
    build()
    assert hashlib.sha256(plugin.read_bytes()).hexdigest() == first
    with zipfile.ZipFile(plugin) as archive:
        assert "src/web_review.py" in archive.namelist()
        assert not any(name.startswith((".private", ".local", ".venv", "tests")) for name in archive.namelist())
        assert json.loads(archive.read("manifest.yaml"))["plugin_api"] == 2
    with zipfile.ZipFile(next((ROOT / "dist").glob("*-bundle.zip"))) as archive:
        assert (archive.getinfo("Start Gateway.command").external_attr >> 16) & 0o111
        assert "locales/zh-CN.json" in archive.namelist()


@pytest.mark.parametrize("value", ["owner/repo", "https://github.com/owner/repo", "https://github.com/owner/repo/"])
def test_repository_input(value):
    assert repository(value) == "owner/repo"


@pytest.mark.parametrize("value", ["https://evil.test/owner/repo", "owner/repo/pull/1", "https://github.com/owner/repo?x=1", "owner/../repo"])
def test_repository_invalid(value):
    with pytest.raises(ValueError):
        repository(value)


@pytest.mark.parametrize("override", [{"maintune_url": "http://remote.test"}, {"maintune_url": "https://user:password@host"},
                                     {"access_token": "short"}, {"bind": "0.0.0.0"}, {"path_secret": "t" * 43}])
def test_gateway_bad_config(override):
    config = {"maintune_url": "http://127.0.0.1:8000", "access_token": "t" * 43, "path_secret": "s" * 43, **override}
    with pytest.raises(ValueError):
        validate_config(config)


def test_first_run_chinese_setup_and_no_overwrite(tmp_path):
    import shutil
    for name in ("gateway.py", "setup_gateway.py", "locales/zh-CN.json"):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    answers = "http://127.0.0.1:8000\nhttps://review.example.test\nhttps://github.com/owner/repo\n"
    run = subprocess.run([sys.executable, "-X", "utf8", "setup_gateway.py"], cwd=tmp_path, input=answers, capture_output=True, encoding="utf-8")
    assert run.returncode == 0, run.stderr
    config_path = tmp_path / ".private" / "gateway.json"
    original = config_path.read_bytes()
    config = json.loads(original)
    validate_config(config)
    connection = (tmp_path / ".private" / "connection.txt").read_text(encoding="utf-8")
    assert config["path_secret"] in connection
    assert config["access_token"] not in connection
    assert config["path_secret"] not in run.stdout
    repeat = subprocess.run([sys.executable, "-X", "utf8", "setup_gateway.py"], cwd=tmp_path, capture_output=True, encoding="utf-8")
    assert repeat.returncode != 0
    assert config_path.read_bytes() == original
