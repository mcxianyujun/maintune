#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"; . "$SCRIPT_DIR/common.sh"
ROOT="$(default_install_root)"; VERSION=""; SOURCE_DIR=""; REPOSITORY="$DEFAULT_REPOSITORY"
while [ "$#" -gt 0 ]; do case "$1" in --install-dir) ROOT="$2"; shift 2;; --version) VERSION="$2"; shift 2;; --source-dir) SOURCE_DIR="$2"; shift 2;; --repository) REPOSITORY="$2"; shift 2;; *) die "Unknown option: $1";; esac; done
[ -n "$VERSION" ] || die "--version is required"
"$SCRIPT_DIR/backup.sh" --install-dir "$ROOT"
args=(--version "$VERSION" --install-dir "$ROOT" --existing-action rebuild --no-open-browser --repository "$REPOSITORY")
[ -z "$SOURCE_DIR" ] || args+=(--source-dir "$SOURCE_DIR")
if ! "$SCRIPT_DIR/install.sh" "${args[@]}"; then
  note "Update failed. The previous version bundle, image and backup were retained. Use restore.sh with the newest backup if data recovery is required."
  exit 1
fi
