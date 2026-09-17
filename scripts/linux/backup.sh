#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"; . "$SCRIPT_DIR/common.sh"
ROOT="$(default_install_root)"; OUTPUT=""
while [ "$#" -gt 0 ]; do case "$1" in --install-dir) ROOT="$2"; shift 2;; --output-dir) OUTPUT="$2"; shift 2;; *) die "Unknown option: $1";; esac; done
assert_docker; need tar; need sha256sum
VERSION_DIR="$(current_version_dir "$ROOT")"; VERSION="$(basename "$VERSION_DIR")"; OUTPUT="${OUTPUT:-$ROOT/backups}"
ENV_FILE="$ROOT/.env"; [ -f "$ENV_FILE" ] || die "Missing installation environment"
DATA_DIR="$(read_env_value "$ENV_FILE" MAINTAINER_DATA_DIR)"; [ -d "$DATA_DIR" ] || die "Missing data directory"
mkdir -p "$OUTPUT"; chmod 700 "$OUTPUT" 2>/dev/null || true
stamp="$(date -u +%Y%m%dT%H%M%SZ)"; base="$OUTPUT/ai-maintainer-$VERSION-$stamp"; archive="$base.tar.gz"
staging="$ROOT/.backup-staging-$stamp"; [ ! -e "$staging" ] || die "Backup staging path already exists"
mkdir -p "$staging/data"
cleanup() { safe_remove_tree "$staging"; }
trap cleanup EXIT
health="$(curl --fail --silent --max-time 5 "http://127.0.0.1:$(read_env_value "$ENV_FILE" MAINTAINER_PORT)/healthz" || true)"
schema="$(printf '%s' "$health" | sed -n 's/.*"schema":\([0-9]*\).*/\1/p')"; schema="${schema:-unknown}"
compose_cmd "$ROOT" "$VERSION_DIR" stop maintainer
trap 'compose_cmd "$ROOT" "$VERSION_DIR" start maintainer >/dev/null 2>&1 || true; cleanup' EXIT
cp "$ENV_FILE" "$staging/.env"
cp -a "$DATA_DIR/." "$staging/data/"
tar -czf "$archive" -C "$staging" .env data
compose_cmd "$ROOT" "$VERSION_DIR" start maintainer
cleanup; trap - EXIT
hash="$(sha256sum "$archive" | awk '{print $1}')"
printf '{"timestamp":"%s","app_version":"%s","schema_version":"%s","sha256":"%s","contains_secrets":true}\n' "$stamp" "$VERSION" "$schema" "$hash" > "$base.manifest.json"
chmod 600 "$archive" "$base.manifest.json" 2>/dev/null || true
note "Backup created: $archive"
note "This backup contains encrypted configuration and internal secrets; store it as sensitive data."
