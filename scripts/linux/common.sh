#!/usr/bin/env bash
set -Eeuo pipefail

PRODUCT="Maintune"
DEFAULT_VERSION="0.1.0-preview.1"
DEFAULT_REPOSITORY="mcxianyujun/maintune"

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
note() { printf '%s\n' "$*"; }
need() { command -v "$1" >/dev/null 2>&1 || die "$1 is required"; }

default_install_root() {
  if [ "$(id -u)" -eq 0 ]; then printf '/opt/ai-maintainer'; else printf '%s/.local/share/ai-maintainer' "$HOME"; fi
}

assert_docker() {
  need docker
  docker version >/dev/null 2>&1 || die "Docker daemon is unavailable or this user lacks permission"
  docker compose version >/dev/null 2>&1 || die "Docker Compose v2 is required"
}

compose_cmd() {
  local root="$1" version_dir="$2"; shift 2
  docker compose --project-name "${MAINTAINER_COMPOSE_PROJECT:-ai-maintainer}" --env-file "$root/.env" -f "$version_dir/compose.yaml" "$@"
}

read_env_value() {
  local file="$1" key="$2" line
  line="$(grep -m1 "^${key}=" "$file" || true)"
  line="${line#*=}"
  line="${line%\"}"; line="${line#\"}"
  printf '%s' "$line"
}

write_env_value() {
  local file="$1" key="$2" value="$3" temporary found=0 line
  temporary="$(mktemp "${file}.XXXXXX")"
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      "$key="*) printf '%s=%s\n' "$key" "$value" >> "$temporary"; found=1;;
      *) printf '%s\n' "$line" >> "$temporary";;
    esac
  done < "$file"
  [ "$found" -eq 1 ] || printf '%s=%s\n' "$key" "$value" >> "$temporary"
  mv "$temporary" "$file"
}

wait_health() {
  local port="$1" attempts="${2:-60}" url
  url="http://127.0.0.1:${port}/healthz"
  for _ in $(seq 1 "$attempts"); do
    if curl --fail --silent --show-error --max-time 3 "$url" >/dev/null 2>&1; then
      curl --fail --silent --show-error --max-time 3 "$url"
      printf '\n'
      return 0
    fi
    sleep 2
  done
  return 1
}

current_version_dir() {
  local root="$1" version
  [ -f "$root/current-version" ] || die "No installed version found in $root"
  version="$(tr -d '\r\n' < "$root/current-version")"
  [ -f "$root/versions/$version/compose.yaml" ] || die "Installed bundle is incomplete: $version"
  printf '%s/versions/%s' "$root" "$version"
}

safe_remove_tree() {
  local target="$1" parent base resolved
  [ -n "$target" ] && [ "$target" != "/" ] || die "Refusing unsafe recursive removal"
  parent="$(cd "$(dirname "$target")" && pwd -P)"; base="$(basename "$target")"
  [ "$base" != "." ] && [ "$base" != ".." ] && [ -n "$base" ] || die "Refusing unsafe recursive removal"
  resolved="$parent/$base"
  rm -rf -- "$resolved"
}
