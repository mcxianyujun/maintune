#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"; . "$SCRIPT_DIR/common.sh"
ROOT="$(default_install_root)"; while [ "$#" -gt 0 ]; do case "$1" in --install-dir) ROOT="$2"; shift 2;; *) die "Unknown option: $1";; esac; done
assert_docker; need curl
VERSION_DIR="$(current_version_dir "$ROOT")"; ENV_FILE="$ROOT/.env"; PORT="$(read_env_value "$ENV_FILE" MAINTAINER_PORT)"; DATA_DIR="$(read_env_value "$ENV_FILE" MAINTAINER_DATA_DIR)"
note "Docker: OK"; docker compose version
compose_cmd "$ROOT" "$VERSION_DIR" config --quiet; note "Compose: OK"
health="$(curl --fail --silent --show-error --max-time 5 "http://127.0.0.1:$PORT/healthz")"; note "Health: $health"
compose_cmd "$ROOT" "$VERSION_DIR" exec -T maintainer pip check
compose_cmd "$ROOT" "$VERSION_DIR" exec -T maintainer python -c "import openhands.sdk; print('OpenHands import: OK')"
free_kb="$(df -Pk "$DATA_DIR" | awk 'NR==2 {print $4}')"; note "Data directory: $DATA_DIR"; note "Free disk KB: $free_kb"; note "Base URL: http://127.0.0.1:$PORT"
