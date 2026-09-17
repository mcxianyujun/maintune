#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/common.sh"

VERSION="$DEFAULT_VERSION"; PORT=8000; INSTALL_ROOT="$(default_install_root)"; DATA_DIR=""; SOURCE_DIR=""; REPOSITORY="$DEFAULT_REPOSITORY"
NO_OPEN=0; NON_INTERACTIVE=0; EXISTING_ACTION=""; INSTALL_DOCKER=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --version) VERSION="$2"; shift 2;;
    --port) PORT="$2"; shift 2;;
    --install-dir) INSTALL_ROOT="$2"; shift 2;;
    --data-dir) DATA_DIR="$2"; shift 2;;
    --source-dir) SOURCE_DIR="$2"; shift 2;;
    --repository) REPOSITORY="$2"; shift 2;;
    --existing-action) EXISTING_ACTION="$2"; shift 2;;
    --no-open-browser) NO_OPEN=1; shift;;
    --non-interactive) NON_INTERACTIVE=1; shift;;
    --install-docker) INSTALL_DOCKER=1; shift;;
    -h|--help) sed -n '1,85p' "$0"; exit 0;;
    *) die "Unknown option: $1";;
  esac
done
[[ "$VERSION" =~ ^[0-9A-Za-z][0-9A-Za-z.-]+$ ]] || die "Invalid version"
[[ "$PORT" =~ ^[0-9]+$ ]] && [ "$PORT" -ge 1 ] && [ "$PORT" -le 65535 ] || die "Invalid port"
[[ "$REPOSITORY" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || die "Invalid GitHub repository"
DATA_DIR="${DATA_DIR:-$INSTALL_ROOT/data}"

if ! command -v docker >/dev/null 2>&1; then
  if [ "$INSTALL_DOCKER" -eq 1 ]; then
    [ "$NON_INTERACTIVE" -eq 0 ] || die "Automatic Docker installation requires an interactive confirmation"
    . /etc/os-release
    case "${ID:-}" in ubuntu|debian) ;; *) die "Automatic Docker installation is supported only on Ubuntu and Debian";; esac
    read -r -p "Install Docker Engine from Docker's official apt repository? [y/N] " answer
    [[ "$answer" =~ ^[Yy]$ ]] || die "Docker installation declined"
    need curl
    sudo install -m 0755 -d /etc/apt/keyrings
    curl -fsSL "https://download.docker.com/linux/$ID/gpg" | sudo tee /etc/apt/keyrings/docker.asc >/dev/null
    sudo chmod a+r /etc/apt/keyrings/docker.asc
    arch="$(dpkg --print-architecture)"
    printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/%s %s stable\n' "$arch" "$ID" "$VERSION_CODENAME" | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
    sudo apt-get update
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  else
    die "Docker is missing. Install Docker Engine and Compose v2, or rerun interactively with --install-docker"
  fi
fi
assert_docker; need curl; need tar; need sha256sum

mkdir -p "$INSTALL_ROOT/versions" "$DATA_DIR" "$INSTALL_ROOT/backups"
INSTALL_ROOT="$(cd "$INSTALL_ROOT" && pwd -P)"
DATA_DIR="$(cd "$DATA_DIR" && pwd -P)"
chmod 700 "$INSTALL_ROOT" "$DATA_DIR" "$INSTALL_ROOT/backups" 2>/dev/null || true
if [ -f "$INSTALL_ROOT/current-version" ]; then
  current="$(tr -d '\r\n' < "$INSTALL_ROOT/current-version")"
  action="${EXISTING_ACTION,,}"
  if [ -z "$action" ] && [ "$NON_INTERACTIVE" -eq 0 ]; then
    read -r -p "Existing installation $current found. Choose repair, rebuild, reconfigure, or abort [abort]: " action
    action="${action:-abort}"
  fi
  [ -n "$action" ] || action=abort
  case "$action" in
    repair|rebuild) ;;
    reconfigure) note "Existing configuration is preserved. Open the Setup Wizard after startup.";;
    abort) die "Installation left unchanged";;
    *) die "Invalid existing action: $action";;
  esac
fi

VERSION_DIR="$INSTALL_ROOT/versions/$VERSION"
rm_stage="$INSTALL_ROOT/.staging-$VERSION"
[ ! -e "$rm_stage" ] || die "Staging path already exists: $rm_stage"
mkdir -p "$rm_stage"
cleanup() { safe_remove_tree "$rm_stage"; }
trap cleanup EXIT

if [ -z "$SOURCE_DIR" ]; then
  candidate="$(cd "$SCRIPT_DIR/../.." && pwd)"
  if [ -f "$candidate/release.json" ] && grep -q "\"version\": \"$VERSION\"" "$candidate/release.json"; then SOURCE_DIR="$candidate"; fi
fi
if [ -n "$SOURCE_DIR" ]; then
  SOURCE_DIR="$(cd "$SOURCE_DIR" && pwd)"
  [ -f "$SOURCE_DIR/Dockerfile" ] && [ -f "$SOURCE_DIR/release.json" ] || die "Source directory is not a release bundle"
  tar -C "$SOURCE_DIR" --exclude=.git --exclude=.env --exclude=data --exclude=backups --exclude=.venv --exclude=node_modules --exclude=.pnpm-store --exclude=test-results -cf - . | tar -C "$rm_stage" -xf -
else
  base="https://github.com/$REPOSITORY/releases/download/v$VERSION"
  archive="maintune-v$VERSION.tar.gz"
  curl -fL --retry 3 --retry-delay 2 -o "$rm_stage/$archive" "$base/$archive"
  curl -fL --retry 3 --retry-delay 2 -o "$rm_stage/SHA256SUMS" "$base/SHA256SUMS"
  expected="$(awk -v f="$archive" '$2==f || $2=="*"f {print $1}' "$rm_stage/SHA256SUMS")"
  [ -n "$expected" ] || die "Checksum entry missing for $archive"
  actual="$(sha256sum "$rm_stage/$archive" | awk '{print $1}')"
  [ "$actual" = "$expected" ] || die "Release checksum verification failed"
  mkdir "$rm_stage/extracted"
  tar -xzf "$rm_stage/$archive" -C "$rm_stage/extracted" --strip-components=1
  rm "$rm_stage/$archive" "$rm_stage/SHA256SUMS"
  cp -a "$rm_stage/extracted/." "$rm_stage/"
  rmdir "$rm_stage/extracted"
fi

[ -f "$rm_stage/requirements.lock" ] || die "Release bundle is incomplete"
[ ! -e "$VERSION_DIR" ] || safe_remove_tree "$VERSION_DIR"
mv "$rm_stage" "$VERSION_DIR"
trap - EXIT

ENV_FILE="$INSTALL_ROOT/.env"
if [ ! -f "$ENV_FILE" ]; then
  umask 077
  admin_token="$(head -c 36 /dev/urandom | base64 | tr '+/' '-_' | tr -d '\r\n')"
  encryption_key="$(head -c 32 /dev/urandom | base64 | tr '+/' '-_' | tr -d '\r\n')"
  cat > "$ENV_FILE" <<EOF
MAINTAINER_ADMIN_TOKEN=$admin_token
MAINTAINER_ENCRYPTION_KEY=$encryption_key
MAINTAINER_VERSION=$VERSION
MAINTAINER_PORT=$PORT
MAINTAINER_BIND_ADDRESS=127.0.0.1
MAINTAINER_DATA_DIR="$DATA_DIR"
MAINTAINER_ENV_FILE="$ENV_FILE"
EOF
  unset admin_token encryption_key
else
  write_env_value "$ENV_FILE" MAINTAINER_VERSION "$VERSION"
  write_env_value "$ENV_FILE" MAINTAINER_PORT "$PORT"
  [ -n "$(read_env_value "$ENV_FILE" MAINTAINER_BIND_ADDRESS)" ] || write_env_value "$ENV_FILE" MAINTAINER_BIND_ADDRESS 127.0.0.1
  write_env_value "$ENV_FILE" MAINTAINER_DATA_DIR "\"$DATA_DIR\""
  write_env_value "$ENV_FILE" MAINTAINER_ENV_FILE "\"$ENV_FILE\""
fi
chmod 600 "$ENV_FILE"

note "Building Maintune $VERSION locally. Internet access to official package sources is required."
compose_cmd "$INSTALL_ROOT" "$VERSION_DIR" build --pull
image_ref="$(compose_cmd "$INSTALL_ROOT" "$VERSION_DIR" config --images | tail -n 1)"
[ -n "$image_ref" ] || die "Built image could not be resolved"
docker image inspect "$image_ref" >/dev/null 2>&1 || die "Built image is unavailable"
docker run --rm --user 0:0 --entrypoint chown -v "$DATA_DIR:/app/data" "$image_ref" -R 10001:10001 /app/data
compose_cmd "$INSTALL_ROOT" "$VERSION_DIR" run --rm --no-deps maintainer pip check
compose_cmd "$INSTALL_ROOT" "$VERSION_DIR" up -d --wait --wait-timeout 120
wait_health "$PORT" 60 || { compose_cmd "$INSTALL_ROOT" "$VERSION_DIR" logs --tail 80 maintainer; die "Health check failed"; }
printf '%s\n' "$VERSION" > "$INSTALL_ROOT/current-version"
note "$PRODUCT $VERSION is running at http://127.0.0.1:$PORT"
note "Open the Web UI and continue with the first-run Setup Wizard. The administrator token remains in the private .env file."
if [ "$NO_OPEN" -eq 0 ] && command -v xdg-open >/dev/null 2>&1; then xdg-open "http://127.0.0.1:$PORT" >/dev/null 2>&1 || true; fi
