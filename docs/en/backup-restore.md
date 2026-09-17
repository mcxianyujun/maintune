# Backup and restore

Run `scripts/windows/backup.ps1` on Windows or `scripts/linux/backup.sh` on Linux. Backup briefly stops the app, archives `.env` and persistent data, writes a version/schema/SHA-256 manifest, and restarts the service. Treat the archive as sensitive because it contains secrets and the encrypted database.

Restore verifies the manifest, stops the service, replaces `data` and `.env`, then starts the app and waits for health. Restore is destructive and requires `-Force` or `--force`. Keep a backup of the current state and never restore a newer schema into an older app without an explicit supported migration path.
