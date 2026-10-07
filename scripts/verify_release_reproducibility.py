"""Build twice and audit source archives from the checked-out candidate."""
from __future__ import annotations

import os
import stat
import subprocess
import tarfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import build_release as builder
import release_audit as audit


def main() -> None:
    epoch = int(subprocess.check_output(
        ["git", "show", "-s", "--format=%ct", "HEAD"], cwd=builder.ROOT
    ).strip())
    os.environ["SOURCE_DATE_EPOCH"] = str(epoch)
    builder.main()
    paths = [builder.OUT / (builder.PREFIX + suffix) for suffix in (".tar.gz", ".zip")]
    first = {path.name: builder.sha256(path) for path in paths}
    first_sums = (builder.OUT / "SHA256SUMS").read_bytes()
    builder.main()
    assert first == {path.name: builder.sha256(path) for path in paths}, "Non-reproducible source archive"
    assert first_sums == (builder.OUT / "SHA256SUMS").read_bytes()
    findings: set[tuple[str, str, str]] = set()

    def check(name: str, data: bytes | None = None) -> None:
        relative = Path(name)
        assert not relative.is_absolute() and ".." not in relative.parts
        assert not any(part in builder.EXCLUDED_PARTS for part in relative.parts), name
        assert relative.suffix.lower() not in builder.EXCLUDED_SUFFIXES, name
        assert not audit.FORBIDDEN_NAMES.search(name), name
        if data is not None:
            audit.scan_bytes(name, data, "source-archive", findings)

    with tarfile.open(paths[0]) as archive:
        for member in archive.getmembers():
            assert member.mtime == epoch, member.name
            assert member.uid == member.gid == 0
            assert not member.issym() and not member.islnk()
            expected_mode = 0o755 if member.isdir() or member.name.endswith(".sh") else 0o644
            assert member.mode == expected_mode
            check(member.name, archive.extractfile(member).read() if member.isfile() else None)
    expected_date = datetime.fromtimestamp(max(epoch, 315532800), timezone.utc).timetuple()[:6]
    # ZIP stores seconds at two-second resolution.
    expected_date = (*expected_date[:5], expected_date[5] // 2 * 2)
    with zipfile.ZipFile(paths[1]) as archive:
        assert archive.testzip() is None
        for info in archive.infolist():
            assert info.date_time == expected_date, info.filename
            mode = stat.S_IMODE(info.external_attr >> 16)
            assert mode == (0o755 if info.filename.endswith(".sh") else 0o644)
            check(info.filename, archive.read(info))
    if findings:
        for source, path, category in sorted(findings):
            print(f"FINDING {category} {path} source={source}")
        raise SystemExit("Archive secret audit failed; values were not printed")
    print(f"Source reproducibility / private exclusion / timestamps / modes / secret scan: PASS epoch={epoch}")


if __name__ == "__main__":
    main()
