# Release security audit

Audit date: 2026-09-16

## Repository state

- The repository has no normal commits yet; all application files are untracked.
- The only `refs/codex/.../base` object is a tree, not a commit.
- Full reachable commit history count: `0`.
- Current release-candidate files scanned: see the reproducible command below.

## Secret scan

Run:

```bash
python scripts/release_audit.py
```

The scanner examines all files Git would add plus every reachable commit and reflog commit. It detects high-confidence private keys and credential formats, and rejects credential/config/database/log/backup file names. It never prints matched values.

The initial scan produced no high-confidence credential finding. The text `-----BEGIN RSA PRIVATE KEY-----` in the GitHub App form is a UI placeholder, not a key block, and is intentionally not treated as a credential.

## Ignore policy

`.gitignore` excludes environment files except `.env.example`, persistent data, backups, databases, logs, archives, private keys, certificates and local build/test output. `.dockerignore` uses an allowlist for the files needed by the application image.

The scan must run again after files are staged and again in release CI. Any real credential found in history blocks release and requires credential rotation plus history remediation.
