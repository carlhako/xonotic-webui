#!/usr/bin/env bash
# Print the CHANGELOG.md section for a version, to publish as its release notes.
#
#   release-notes.sh <version> [changelog]
#
# <version> may carry a leading "v" (a tag). The section is everything between
# "## <version>" and the next "## " heading, with surrounding blank lines
# trimmed. Exits non-zero, naming the version, when the section is missing or
# empty, so a release is never published without notes.
set -euo pipefail

if [[ $# -lt 1 || -z "$1" ]]; then
  echo "usage: $0 <version> [changelog]" >&2
  exit 2
fi
version="${1#v}"
changelog="${2:-$(dirname "$0")/../../CHANGELOG.md}"

if [[ ! -f "$changelog" ]]; then
  echo "no changelog at $changelog" >&2
  exit 1
fi

notes="$(
  awk -v want="$version" '
    /^## / {
      if (found) exit
      # "## 0.5.1 - 2026-09-24" or "## 0.5.1": match the version exactly.
      split(substr($0, 4), words, /[ \t]/)
      if (words[1] == want) { found = 1; next }
    }
    found { print }
  ' "$changelog" | sed -e '/./,$!d'
)"

if [[ -z "${notes//[[:space:]]/}" ]]; then
  echo "no CHANGELOG.md entry for $version (add a '## $version - <date>' section)" >&2
  exit 1
fi
printf '%s\n' "$notes"
