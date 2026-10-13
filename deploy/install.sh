#!/usr/bin/env bash
# xonotic-webui installer for Debian 12/13 on amd64 (a Proxmox LXC works), run as root.
#
# It installs the runtime packages, creates an unprivileged service user, downloads and
# verifies the pinned Xonotic 0.8.6 release, installs the panel from its GitHub release
# (a wheel with the prebuilt web interface: no Node and no compiler on this machine),
# installs and starts the hardened systemd unit, and waits for the panel's health check.
#
# Re-running it is the upgrade and repair path. The server configuration, panel state
# and logs are never touched; the game is only fetched if it is missing; the new
# application is built beside the old one and swapped in, and rolled back if the new
# panel does not come up.
#
# Usage (as root; a minimal LXC lacks curl, so `apt-get install -y curl` first):
#   curl -fsSL https://github.com/carlhako/xonotic-webui/releases/latest/download/install.sh | bash
#   RELEASE_TAG=v0.1.0 bash install.sh                     # pin a panel release
#   XONOTIC_WEBUI_TARBALL=/path/xonotic-webui.tar.gz bash install.sh   # offline panel
#   XONOTIC_ARCHIVE=/path/xonotic-0.8.6.zip bash install.sh            # offline game
#
# The whole script is wrapped in functions and only `main` is called, on the last line,
# so a truncated download never runs a half-script.

set -euo pipefail

# --- constants (single place; rename here only, see design D16) -----------------
APP_NAME="xonotic-webui"
PKG_NAME="${APP_NAME//-/_}"          # the Python package / wheel name
ENV_PREFIX="XONOTIC_WEBUI_"          # prefix of the panel's (and this script's) variables
GITHUB_REPO="carlhako/xonotic-webui"

# Pinned game release (design D13). Digest computed over the complete archive.
XONOTIC_VERSION="0.8.6"
XONOTIC_URL="https://dl.xonotic.org/xonotic-${XONOTIC_VERSION}.zip"
XONOTIC_SHA256="50850f8d800e7499722f6ea61e478e96464a375494b5a24da93aa0598cbe964d"
XONOTIC_SIZE_BYTES=1238439495
XONOTIC_ZIP_TOPDIR="Xonotic"
# Archive (1.24 GB) + extracted tree (~1.1 GB) + margin, from the spike (design D5).
MIN_FREE_BYTES=$((3 * 1024 * 1024 * 1024))

# --- layout -----------------------------------------------------------------------
# DESTDIR is the usual packaging prefix (empty in production). It exists so the
# individual steps can be exercised in a scratch tree without root.
DESTDIR="${DESTDIR:-}"
PREFIX="${DESTDIR}/opt/${APP_NAME}"
GAME_PARENT="${DESTDIR}/opt/xonotic"
GAME_DIR="${GAME_PARENT}/${XONOTIC_VERSION}"
STATE_DIR="${DESTDIR}/var/lib/${APP_NAME}"
USERDIR="${STATE_DIR}/userdir"
ETC_DIR="${DESTDIR}/etc/${APP_NAME}"
ENV_FILE="${ETC_DIR}/${APP_NAME}.env"
UNIT_DIR="${DESTDIR}/etc/systemd/system"
CACHE_DIR="${DESTDIR}/var/cache/${APP_NAME}"
SERVICE_USER="${APP_NAME}"
OS_RELEASE_FILE="${OS_RELEASE_FILE:-/etc/os-release}"

# opt NAME: the value of ${ENV_PREFIX}NAME from the environment, or empty.
opt() { local v="${ENV_PREFIX}$1"; printf '%s' "${!v:-}"; }

REPO="$(opt REPO)"
REPO="${REPO:-$GITHUB_REPO}"
RELEASE_TAG="${RELEASE_TAG:-latest}"

log()  { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!! \033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31mXX \033[0m %s\n' "$*" >&2; exit 1; }

# --- preflight: nothing is changed until all of this has passed -------------------
require_root() {
  [ "$(id -u)" -eq 0 ] || die "this installer must be run as root"
}

require_platform() {
  local arch
  arch="$(uname -m)"
  case "$arch" in
    x86_64|amd64) ;;
    *) die "unsupported architecture '$arch': the Xonotic dedicated server release is for 64-bit x86 (x86_64/amd64) only" ;;
  esac

  local id="" id_like=""
  if [ -r "$OS_RELEASE_FILE" ]; then
    # shellcheck source=/dev/null
    id="$(. "$OS_RELEASE_FILE" && echo "${ID:-}")"
    # shellcheck source=/dev/null
    id_like="$(. "$OS_RELEASE_FILE" && echo "${ID_LIKE:-}")"
  fi
  case " $id $id_like " in
    *" debian "*) ;;
    *) die "unsupported system '${id:-unknown}': a Debian-family system (Debian 12/13) is required" ;;
  esac
  command -v apt-get >/dev/null 2>&1 || die "apt-get was not found: a Debian-family system with apt is required"
}

# Free bytes on the filesystem that will hold $1 (its nearest existing ancestor).
free_bytes_for() {
  local path="$1"
  while [ ! -e "$path" ] && [ "$path" != "/" ]; do path="$(dirname "$path")"; done
  df -P -B1 "$path" | awk 'NR==2 {print $4}'
}

game_installed() {
  [ -x "$GAME_DIR/xonotic-linux64-dedicated" ] && [ -d "$GAME_DIR/data" ]
}

require_space() {
  game_installed && return 0
  local free
  free="$(free_bytes_for "$GAME_PARENT")"
  if [ "${free:-0}" -lt "$MIN_FREE_BYTES" ]; then
    die "not enough disk space for the game files under $GAME_PARENT: need $((MIN_FREE_BYTES / 1024 / 1024)) MiB, only $((free / 1024 / 1024)) MiB available"
  fi
}

# --- system setup -----------------------------------------------------------------
install_packages() {
  log "installing runtime packages"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  # python3-venv: the app's virtualenv. curl/unzip/ca-certificates: downloads. libstdc++6
  # and zlib1g: the only shared libraries the dedicated binary needs that a minimal LXC
  # may lack (design, Spike findings).
  apt-get install -y -qq python3 python3-venv curl unzip ca-certificates libstdc++6 zlib1g >/dev/null
}

ensure_user() {
  if ! id "$SERVICE_USER" >/dev/null 2>&1; then
    log "creating service user '$SERVICE_USER'"
    useradd --system --user-group --home-dir "/var/lib/${APP_NAME}" --shell /usr/sbin/nologin "$SERVICE_USER"
  fi
}

# Application and game are root-owned (the service user cannot modify them); only the
# state directory is the service user's.
ensure_dirs() {
  log "creating directory layout"
  install -d -m 0755 -o root -g root "$PREFIX" "$GAME_PARENT"
  install -d -m 0755 -o "$SERVICE_USER" -g "$SERVICE_USER" "$STATE_DIR" "$USERDIR" "$USERDIR/data"
  install -d -m 0755 -o root -g root "$ETC_DIR" "$CACHE_DIR"
}

# Entries under $1 that the service user could change: not owned by root, or writable by
# group/other (symlinks carry no mode of their own). Prints the first, if any.
tampering_risk() {
  [ -e "$1" ] || return 0
  find "$1" \( ! -uid 0 -o \( ! -type l -a -perm /022 \) \) -print -quit
}

# Re-runs are the repair path: put the root-owned trees back to root-owned and
# not group/other-writable, and give the state directory back to the service user, in case
# a previous run, an unzip or a hand edit as root left them otherwise. Contents are never
# rewritten, only their ownership and mode.
repair_ownership() {
  local p
  for p in "$PREFIX" "$GAME_PARENT"; do
    if [ -n "$(tampering_risk "$p")" ]; then
      log "restoring root ownership of $p"
      chown -R root:root "$p"
      chmod -R go-w "$p"
    fi
  done
  if [ -n "$(find "$STATE_DIR" ! -user "$SERVICE_USER" -print -quit)" ]; then
    log "restoring ownership of $STATE_DIR to $SERVICE_USER"
    chown -R "$SERVICE_USER:$SERVICE_USER" "$STATE_DIR"
  fi
}

# Run "$@" as the service user with no supplementary groups (the least it can ever have).
as_service_user() {
  setpriv --reuid "$(id -u "$SERVICE_USER")" --regid "$(id -g "$SERVICE_USER")" \
    --clear-groups -- "$@"
}

# Prove the layout rather than assume it: the application and game trees are root's and
# the service user can neither write to them nor leave anything behind in them, while it
# can write its own state and read and run what it needs. Fails before the service is
# touched.
verify_layout() {
  local p risk
  for p in "$PREFIX" "$GAME_PARENT" "$ETC_DIR"; do
    [ -d "$p" ] || die "layout check: $p is missing"
    [ "$(stat -c %u "$p")" -eq 0 ] || die "layout check: $p is not owned by root"
    risk="$(tampering_risk "$p")"
    [ -z "$risk" ] || die "layout check: $risk is changeable by the service user"
    if as_service_user test -w "$p"; then
      die "layout check: the service user can write to $p"
    fi
    as_service_user test -x "$p" || die "layout check: the service user cannot enter $p"
  done
  if [ -x "$GAME_DIR/xonotic-linux64-dedicated" ]; then
    as_service_user test -x "$GAME_DIR/xonotic-linux64-dedicated" \
      || die "layout check: the service user cannot run the game server"
  fi
  for p in "$STATE_DIR" "$USERDIR" "$USERDIR/data"; do
    as_service_user test -w "$p" || die "layout check: the service user cannot write to $p"
  done
}

# --- the game ---------------------------------------------------------------------
sha256_of() { sha256sum "$1" | awk '{print $1}'; }

# Verify $1 against the pinned digest; on mismatch remove anything unverified and fail.
# $2=1 means the archive is our own download, which is then deleted too (a corrupt cache
# must not be resumed into forever); a user-supplied archive is never deleted.
verify_archive() {
  local archive="$1" ours="${2:-0}" actual
  actual="$(sha256_of "$archive")"
  if [ "$actual" != "$XONOTIC_SHA256" ]; then
    rm -rf "${GAME_PARENT}/.staging-${XONOTIC_VERSION}"
    if [ "$ours" -eq 1 ]; then rm -f "$archive"; fi
    die "game archive digest mismatch: expected $XONOTIC_SHA256, got $actual ($archive)"
  fi
}

# Extract only what the dedicated server needs (design, Spike findings): the binary, the
# public key and data/ without the client music pack. Staged beside the destination and
# moved into place only after verification, so no unverified file is ever left there.
extract_game() {
  local archive="$1" staging="${GAME_PARENT}/.staging-${XONOTIC_VERSION}" top="$XONOTIC_ZIP_TOPDIR"
  rm -rf "$staging"
  mkdir -p "$staging"
  log "extracting the game (about 1.1 GB)"
  unzip -q "$archive" \
    "${top}/xonotic-linux64-dedicated" "${top}/key_0.d0pk" "${top}/data/*" \
    -x "${top}/data/*-music.pk3" -d "$staging" \
    || { rm -rf "$staging"; die "could not extract the game archive"; }
  [ -f "$staging/$top/xonotic-linux64-dedicated" ] \
    || { rm -rf "$staging"; die "the game archive has no dedicated server binary"; }
  chmod 0755 "$staging/$top/xonotic-linux64-dedicated"
  rm -rf "$GAME_DIR"
  mv "$staging/$top" "$GAME_DIR"
  rmdir "$staging"
  chown -R root:root "$GAME_DIR" 2>/dev/null || true
}

install_game() {
  if game_installed; then
    log "game ${XONOTIC_VERSION} already installed; not downloading it again"
    return 0
  fi
  local archive="" downloaded=0
  if [ -n "${XONOTIC_ARCHIVE:-}" ]; then
    [ -f "$XONOTIC_ARCHIVE" ] || die "XONOTIC_ARCHIVE does not exist: $XONOTIC_ARCHIVE"
    log "using local game archive $XONOTIC_ARCHIVE"
    archive="$XONOTIC_ARCHIVE"
  else
    archive="${CACHE_DIR}/xonotic-${XONOTIC_VERSION}.zip"
    downloaded=1
    local have=0
    [ -f "$archive" ] && have="$(stat -c %s "$archive")"
    if [ "$have" -ne "$XONOTIC_SIZE_BYTES" ]; then
      log "downloading Xonotic ${XONOTIC_VERSION} (1.2 GB; resumable)"
      curl -fL --retry 5 --retry-delay 3 -C - -o "$archive" "$XONOTIC_URL" \
        || die "could not download $XONOTIC_URL (re-run to resume)"
    fi
  fi
  verify_archive "$archive" "$downloaded"
  extract_game "$archive"
  if [ "$downloaded" -eq 1 ]; then rm -f "$archive"; fi
  log "game installed to $GAME_DIR"
}

# --- configuration ------------------------------------------------------------------
# A minimal working server.cfg, only when none exists; an existing one is never touched.
seed_server_cfg() {
  local cfg="${USERDIR}/data/server.cfg"
  if [ -e "$cfg" ]; then
    log "keeping the existing server.cfg"
    return 0
  fi
  log "seeding a first-run server.cfg"
  cat >"$cfg" <<'CFG'
// Seeded by the xonotic-webui installer on first install and never overwritten.
// Edit freely: the panel runs this file, then forces the few settings it depends on.
hostname "Xonotic WebUI Server"
sv_public 0
maxplayers 16

// The panel learns who is connected and what map is running from the event log.
sv_eventlog 1
sv_eventlog_console 1
CFG
  chown "$SERVICE_USER:$SERVICE_USER" "$cfg"
  chmod 0644 "$cfg"
}

seed_env_file() {
  [ -e "$ENV_FILE" ] && return 0
  cat >"$ENV_FILE" <<'ENV'
# Optional overrides for xonotic-webui, read by the systemd unit. Uncomment to change.
#XONOTIC_WEBUI_PORT=80
#XONOTIC_WEBUI_GAME_PORT=26000
# If you raise the shutdown timeout, raise TimeoutStopSec in the unit by the same amount.
#XONOTIC_WEBUI_SHUTDOWN_TIMEOUT=60
ENV
  chmod 0644 "$ENV_FILE"
}

env_value() {  # env_value KEY DEFAULT
  local v
  v="$(sed -n "s/^$1=//p" "$ENV_FILE" 2>/dev/null | tail -n1 | tr -d "\"' ")"
  echo "${v:-$2}"
}

# --- the panel ------------------------------------------------------------------------
WORK=""
fetch_release() {
  WORK="$(mktemp -d)"
  local tarball
  tarball="$(opt TARBALL)"
  if [ -n "$tarball" ]; then
    [ -f "$tarball" ] || die "${ENV_PREFIX}TARBALL does not exist: $tarball"
    log "using local release tarball $tarball"
    tar -xzf "$tarball" -C "$WORK"
  else
    local base
    if [ "$RELEASE_TAG" = "latest" ]; then
      base="https://github.com/${REPO}/releases/latest/download"
    else
      base="https://github.com/${REPO}/releases/download/${RELEASE_TAG}"
    fi
    log "downloading the panel release from $base"
    curl -fsSL "${base}/${APP_NAME}.tar.gz" -o "$WORK/${APP_NAME}.tar.gz" \
      || die "could not download the release tarball from $base"
    tar -xzf "$WORK/${APP_NAME}.tar.gz" -C "$WORK"
  fi
  SRC="$WORK/${APP_NAME}"
  WHEEL=""
  local candidate
  for candidate in "$SRC"/dist/"${PKG_NAME}"-*-py3-none-any.whl; do
    [ -f "$candidate" ] && { WHEEL="$candidate"; break; }
  done
  [ -n "$WHEEL" ] || die "the release tarball has no ${APP_NAME} wheel"
  NEW_VERSION="$(basename "$WHEEL" | sed -E "s/^${PKG_NAME}-([^-]+)-.*/\\1/")"
}

# Build the new virtualenv beside the live one so a failed build leaves the running
# panel untouched.
build_venv() {
  NEW_VENV="$PREFIX/venv.new"
  rm -rf "$NEW_VENV"
  log "creating the virtualenv and installing ${APP_NAME} ${NEW_VERSION}"
  python3 -m venv "$NEW_VENV"
  "$NEW_VENV/bin/python" -m pip install --quiet --upgrade pip
  # Installed by path, never by bare name. --only-binary=:all: is the "no compiler on
  # this host" guarantee: every dependency is a prebuilt wheel or the install fails.
  local wheelhouse
  wheelhouse="$(opt WHEELHOUSE)"
  if [ -n "$wheelhouse" ]; then
    "$NEW_VENV/bin/python" -m pip install --quiet --only-binary=:all: --no-index \
      --find-links "$wheelhouse" "$WHEEL"
  else
    "$NEW_VENV/bin/python" -m pip install --quiet --only-binary=:all: "$WHEEL"
  fi
}

wait_healthy() {
  local port url state
  port="$(env_value "${ENV_PREFIX}PORT" 80)"
  url="http://127.0.0.1:${port}/health"
  for _ in $(seq 1 60); do
    if curl -fsS --max-time 2 "$url" 2>/dev/null | grep -q "\"version\":\"${NEW_VERSION}\""; then
      return 0
    fi
    state="$(systemctl show -p ActiveState --value "${APP_NAME}.service" 2>/dev/null || true)"
    [ "$state" = "failed" ] && return 1
    sleep 1
  done
  return 1
}

# Stop, swap the venv, start, health-check, and roll back on failure.
swap_and_start() {
  local unit="${UNIT_DIR}/${APP_NAME}.service" had_previous=0
  [ -d "$PREFIX/venv" ] && had_previous=1

  log "stopping ${APP_NAME}"
  systemctl stop "${APP_NAME}.service" 2>/dev/null || true
  if [ "$had_previous" -eq 1 ]; then
    rm -rf "$PREFIX/venv.old"
    mv "$PREFIX/venv" "$PREFIX/venv.old"
    [ -f "$unit" ] && cp -a "$unit" "$unit.old"
  fi
  mv "$NEW_VENV" "$PREFIX/venv"
  # Re-point the venv's scripts (shebangs, activate) at its final path.
  { grep -rlI -- "$NEW_VENV" "$PREFIX/venv/bin" 2>/dev/null || true; } \
    | xargs -r sed -i "s|$NEW_VENV|$PREFIX/venv|g"

  log "installing ${APP_NAME}.service"
  install -d -m 0755 "$UNIT_DIR"
  install -m 0644 "$SRC/deploy/${APP_NAME}.service" "$unit"
  systemctl daemon-reload
  systemctl enable "${APP_NAME}.service"
  systemctl start "${APP_NAME}.service"

  log "waiting for ${APP_NAME} ${NEW_VERSION} to answer"
  if wait_healthy; then
    rm -rf "$PREFIX/venv.old" "$unit.old"
    return 0
  fi
  if [ "$had_previous" -eq 1 ]; then
    warn "${APP_NAME} ${NEW_VERSION} did not start; restoring the previous version"
    systemctl stop "${APP_NAME}.service" 2>/dev/null || true
    rm -rf "$PREFIX/venv.failed"
    mv "$PREFIX/venv" "$PREFIX/venv.failed"
    mv "$PREFIX/venv.old" "$PREFIX/venv"
    [ -f "$unit.old" ] && mv "$unit.old" "$unit"
    systemctl daemon-reload
    systemctl start "${APP_NAME}.service"
    rm -rf "$PREFIX/venv.failed"
    die "installing ${APP_NAME} ${NEW_VERSION} failed; the previous version is running again (journalctl -u ${APP_NAME})"
  fi
  die "${APP_NAME} ${NEW_VERSION} did not start (journalctl -u ${APP_NAME})"
}

report() {
  local ip port game_port url
  ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
  ip="${ip:-$(hostname)}"
  port="$(env_value "${ENV_PREFIX}PORT" 80)"
  game_port="$(env_value "${ENV_PREFIX}GAME_PORT" 26000)"
  if [ "$port" = "80" ]; then url="http://${ip}/"; else url="http://${ip}:${port}/"; fi
  log "done: ${APP_NAME} ${NEW_VERSION} is running"
  log "web interface:  ${url}"
  log "game port:      UDP ${game_port} (open it for players to join)"
}

cleanup() { [ -n "$WORK" ] && rm -rf "$WORK"; return 0; }

main() {
  require_root
  require_platform
  require_space
  trap cleanup EXIT

  install_packages
  ensure_user
  ensure_dirs
  install_game
  repair_ownership
  seed_server_cfg
  seed_env_file
  fetch_release
  build_venv
  verify_layout
  swap_and_start
  report
}

# Run only when executed (or piped to bash), not when sourced by the tests.
if [ "${BASH_SOURCE[0]:-$0}" = "$0" ]; then
  main "$@"
fi
