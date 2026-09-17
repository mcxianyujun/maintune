#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"; . "$SCRIPT_DIR/common.sh"
ROOT="$(default_install_root)"; PURGE=0; FORCE=0
while [ "$#" -gt 0 ]; do case "$1" in --install-dir) ROOT="$2"; shift 2;; --purge-data) PURGE=1; shift;; --force) FORCE=1; shift;; *) die "Unknown option: $1";; esac; done
VERSION_DIR="$(current_version_dir "$ROOT")"; assert_docker; compose_cmd "$ROOT" "$VERSION_DIR" down --remove-orphans
if [ "$PURGE" -eq 1 ]; then
  [ "$FORCE" -eq 1 ] || die "Purging data and secrets is irreversible. Rerun with --purge-data --force"
  data="$(read_env_value "$ROOT/.env" MAINTAINER_DATA_DIR)"
  case "$data" in "$ROOT"/*) safe_remove_tree "$data";; *) die "Refusing to purge data outside the installation root";; esac
  rm -f -- "$ROOT/.env"
  note "Application and persistent data removed. Version bundles and backups remain in $ROOT."
else
  note "Application stopped and containers removed. Data, secrets, bundles and backups were preserved in $ROOT."
fi
