#!/usr/bin/env bash
set -euo pipefail
cd /opt/ai-maintainer
if [ ! -e .env ]; then
  umask 077
  python3 - <<'PY'
import secrets, base64, os
from pathlib import Path
with Path('.env').open('x') as file:
    file.write('MAINTAINER_ADMIN_TOKEN=' + secrets.token_urlsafe(36) + '\n')
    file.write('MAINTAINER_ENCRYPTION_KEY=' + base64.urlsafe_b64encode(os.urandom(32)).decode() + '\n')
PY
fi
chmod 600 .env
docker compose up -d --no-build --wait --wait-timeout 90
docker compose ps
curl --fail --silent http://127.0.0.1:8000/healthz
printf '\n'
