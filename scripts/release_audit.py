"""Fail-closed release scan without printing credential values.

Scans files that Git would include and every reachable commit. Findings contain
only a category, path and optional commit id; matched content is never printed.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    "private-key": re.compile(
        rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----\s*[A-Za-z0-9+/=\r\n]{40,}"
    ),
    "github-token": re.compile(rb"(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})"),
    "aws-access-key": re.compile(rb"AKIA[0-9A-Z]{16}"),
    "jwt": re.compile(rb"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}"),
}
FORBIDDEN_NAMES = re.compile(
    r"(^|/)(?:\.env(?:\.(?!example$).+)?|[^/]*(?:\.sqlite3?|\.db|\.pem|\.p12|\.pfx|\.log)|"
    r"id_(?:rsa|ed25519)[^/]*|(?:data|backup|backups)(?:/|$)|(?:credentials?|secrets?)\.(?:json|ya?ml|txt))$",
    re.IGNORECASE,
)
MAX_FILE = 10 * 1024 * 1024


def git(*args: str, binary: bool = False) -> bytes | str:
    result = subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True,
        text=not binary, encoding=None if binary else "utf-8", errors=None if binary else "replace",
    )
    return result.stdout


def scan_bytes(path: str, data: bytes, source: str, findings: set[tuple[str, str, str]]) -> None:
    if len(data) > MAX_FILE or b"\x00" in data:
        return
    for category, pattern in PATTERNS.items():
        if pattern.search(data):
            findings.add((source, path, category))


def current_files() -> list[str]:
    output = git("ls-files", "--cached", "--others", "--exclude-standard", "-z", binary=True)
    return [item.decode("utf-8", "surrogateescape") for item in output.split(b"\0") if item]


def scan_current(findings: set[tuple[str, str, str]]) -> int:
    files = current_files()
    for name in files:
        normalized = name.replace("\\", "/")
        if FORBIDDEN_NAMES.search(normalized):
            findings.add(("working-tree", normalized, "forbidden-release-file"))
        path = ROOT / name
        if path.is_file():
            scan_bytes(normalized, path.read_bytes(), "working-tree", findings)
    return len(files)


def scan_history(findings: set[tuple[str, str, str]]) -> int:
    commits = list(dict.fromkeys(str(git("rev-list", "--all", "--reflog")).splitlines()))
    seen_blobs: set[str] = set()
    for commit in commits:
        listing = str(git("ls-tree", "-r", "--full-tree", commit))
        for line in listing.splitlines():
            meta, path = line.split("\t", 1)
            _mode, kind, object_id = meta.split()
            if kind != "blob":
                continue
            normalized = path.replace("\\", "/")
            if FORBIDDEN_NAMES.search(normalized):
                findings.add((commit[:12], normalized, "forbidden-release-file"))
            if object_id in seen_blobs:
                continue
            seen_blobs.add(object_id)
            size = int(str(git("cat-file", "-s", object_id)).strip())
            if size <= MAX_FILE:
                scan_bytes(normalized, git("cat-file", "blob", object_id, binary=True), commit[:12], findings)
    return len(commits)


def main() -> int:
    findings: set[tuple[str, str, str]] = set()
    files = scan_current(findings)
    commits = scan_history(findings)
    print(f"release-audit: current-files={files} history-commits={commits}")
    if findings:
        for source, path, category in sorted(findings):
            print(f"FINDING {category} {path} source={source}")
        print(f"release-audit: FAILED ({len(findings)} finding(s)); values were redacted")
        return 1
    print("release-audit: PASS (no high-confidence secret or forbidden release file found)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
