# Linux deployment

Ubuntu 24.04 LTS is the acceptance target; Debian 12+ is best effort. Use at least 2 CPU cores, 4 GB RAM, and 15 GB free disk space. Install Docker Engine, Docker Compose v2, `curl`, `tar`, and `sha256sum`.

```bash
chmod +x scripts/linux/*.sh
./scripts/linux/install.sh --port 8000
```

The default bind address is `127.0.0.1`. The script creates `.env` with mode 600 and never replaces existing secrets. Open `http://127.0.0.1:8000`, read the administrator token from `.env`, and finish the Setup Wizard. Use an HTTPS reverse proxy for public access.

```bash
./scripts/linux/doctor.sh
./scripts/linux/backup.sh
./scripts/linux/update.sh --version 0.1.0-preview.2
./scripts/linux/restore.sh --backup /path/to/backup
```

Updates back up data before building. A failed update preserves the previous version, image, and backup. Local Sandbox is not a strong isolation boundary; use Shipyard Neo for untrusted repositories.
