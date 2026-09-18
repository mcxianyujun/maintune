# Windows 11 deployment

Requires Windows 11, Docker Desktop with the WSL2 backend, Docker Compose v2, and preferably PowerShell 7.

```powershell
docker version
docker compose version
.\scripts\windows\install.ps1 -Port 8000
```

The installer creates `.env`, builds locally, runs `pip check`, starts the service, and waits for health. It does not install Docker silently or replace existing secrets. Open the browser, read the administrator token from the private `.env`, and complete the Setup Wizard.

```powershell
.\scripts\windows\doctor.ps1
.\scripts\windows\backup.ps1
.\scripts\windows\update.ps1 -Version 0.1.0-preview.2
.\scripts\windows\restore.ps1 -BackupPath C:\path\to\backup
```

Do not delete `data`, `.env`, or `backups`. Windows scripts have automated syntax and path checks; a final fresh Windows 11 + Docker Desktop E2E remains a manual Preview verification item.
