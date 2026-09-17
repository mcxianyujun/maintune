# Docker Compose

SQLite, encrypted settings, runtime files, and run records persist in `data/`. The image is built locally from `requirements.lock` and the current source.

```bash
cp .env.example .env
mkdir -p data
sudo chown -R 10001:10001 data
docker compose build --pull
docker compose run --rm --no-deps maintainer pip check
docker compose up -d --wait
curl --fail http://127.0.0.1:8000/healthz
```

Set `MAINTAINER_ADMIN_TOKEN` and `MAINTAINER_ENCRYPTION_KEY`. Optional deployment variables include `MAINTAINER_BIND_ADDRESS`, `MAINTAINER_PORT`, and `MAINTAINER_DATA_DIR`.

```bash
docker compose stop
docker compose down
```

Never add `-v` to `docker compose down`. Back up `data/` and `.env` before updates or restores. Never commit secrets, data, logs, backups, or diagnostic output.
