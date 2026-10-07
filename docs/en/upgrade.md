# Upgrade

Run the platform `update` script with the target version. It backs up first, downloads and verifies the release bundle, builds locally, preserves data, applies migrations, recreates the service, and runs health checks.

On failure, the previous bundle, image, and backup remain available. Do not automatically downgrade the database. Use the restore script and a matching application version. Standard proxy variables are forwarded to Docker build.

## Preview 3 → v0.1.0 Stable candidate

The candidate remains unpublished: do not expect the v0.1.0 download URL to exist yet. Use `--source-dir` (Linux) or `-SourceDirectory` (Windows) with a verified RC source bundle for isolated validation. After release, specify version `0.1.0` to the update script.

Database schema remains v4; no new Stable migration is introduced. Preserve the original `.env`, encryption key, database, plugin configuration and `data/plugins/data/` contents together. Back up before upgrade; retaining the encryption key is required to decrypt existing secrets. Existing v1 `.mtp` packages remain supported; v2 Agent Tools remain limited to `code_worker`. Unknown GitHub writes must be reconciled by an administrator before retry; see [review recovery](../operations/review-recovery.md). No production upgrade is performed by this RC audit.
