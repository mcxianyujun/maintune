#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"; . "$SCRIPT_DIR/common.sh"
ROOT="$(default_install_root)"; BACKUP=""; FORCE=0
while [ "$#" -gt 0 ]; do case "$1" in --install-dir) ROOT="$2"; shift 2;; --backup) BACKUP="$2"; shift 2;; --force) FORCE=1; shift;; *) die "Unknown option: $1";; esac; done
[ -n "$BACKUP" ] && [ -f "$BACKUP" ] || die "--backup must name an existing .tar.gz"
[ "$FORCE" -eq 1 ] || die "Restore replaces current data and secrets. Review the backup, then rerun with --force"
assert_docker; need sha256sum
manifest="${BACKUP%.tar.gz}.manifest.json"; [ -f "$manifest" ] || die "Backup manifest is missing"
expected="$(sed -n 's/.*"sha256":"\([a-f0-9]*\)".*/\1/p' "$manifest")"; actual="$(sha256sum "$BACKUP" | awk '{print $1}')"
[ -n "$expected" ] && [ "$actual" = "$expected" ] || die "Backup checksum verification failed"
VERSION_DIR="$(current_version_dir "$ROOT")"; compose_cmd "$ROOT" "$VERSION_DIR" down
staging="$ROOT/.restore-staging"; [ ! -e "$staging" ] || die "Restore staging path already exists"; mkdir "$staging"
tar -xzf "$BACKUP" -C "$staging"
[ -f "$staging/.env" ] && [ -d "$staging/data" ] || die "Backup content is incomplete"
old_data="$(read_env_value "$ROOT/.env" MAINTAINER_DATA_DIR)"
[ -n "$old_data" ] || die "Current data directory is missing from the environment"
safe_remove_tree "$old_data"; mkdir -p "$(dirname "$old_data")"; mv "$staging/data" "$old_data"; mv "$staging/.env" "$ROOT/.env"; rmdir "$staging"; chmod 600 "$ROOT/.env"
compose_cmd "$ROOT" "$VERSION_DIR" up -d --wait --wait-timeout 120
port="$(read_env_value "$ROOT/.env" MAINTAINER_PORT)"; wait_health "$port" 60 >/dev/null || die "Restored service did not become healthy"
note "Restore completed and health check passed."
