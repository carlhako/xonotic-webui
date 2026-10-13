#!/usr/bin/env bash
# xonotic-webui installer. Run as root on Debian 12/13 (amd64). Re-running upgrades.
#
# Skeleton: the constants below are final; the install logic is added by the
# installer tasks of the bootstrap-xonotic-webui change (group 9).
set -euo pipefail

# --- constants (single place; rename here only, see design D16) -----------------
APP_NAME="xonotic-webui"
GITHUB_REPO="carlhako/xonotic-webui"

# Pinned game release (design D13). Digest computed over the complete archive.
XONOTIC_VERSION="0.8.6"
XONOTIC_URL="https://dl.xonotic.org/xonotic-${XONOTIC_VERSION}.zip"
XONOTIC_SHA256="50850f8d800e7499722f6ea61e478e96464a375494b5a24da93aa0598cbe964d"
XONOTIC_SIZE_BYTES=1238439495
XONOTIC_ZIP_TOPDIR="Xonotic"
# Archive (1.24 GB) + extracted tree (~1.1 GB) + margin, from the spike (design D5).
MIN_FREE_BYTES=$((3 * 1024 * 1024 * 1024))
