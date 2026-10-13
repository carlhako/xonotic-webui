#!/usr/bin/env bash
# Assemble the release assets from a built wheel (dist/xonotic_webui-*.whl):
#
#   <outdir>/xonotic-webui.tar.gz   wheel + README + LICENSE + deploy assets
#   <outdir>/install.sh             the installer, as a standalone download
#
# Used by the release workflow and by the tests, so both exercise the same guards:
# the wheel must carry the prebuilt web interface, and no frontend source may ship.
#
#   scripts/assemble-release.sh [outdir]
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
# The name comes from the installer's single constant (design D16).
app="$(sed -n 's/^APP_NAME="\(.*\)"$/\1/p' "$root/deploy/install.sh")"
[ -n "$app" ] || { echo "could not read APP_NAME from deploy/install.sh" >&2; exit 1; }
pkg="${app//-/_}"
out="${1:-$root/release}"
mkdir -p "$out"
out="$(cd "$out" && pwd)"

wheel=""
for candidate in "$root"/dist/"$pkg"-*-py3-none-any.whl; do
  [ -f "$candidate" ] && { wheel="$candidate"; break; }
done
[ -n "$wheel" ] || { echo "no wheel in $root/dist (run: python -m build --wheel)" >&2; exit 1; }

# The wheel must contain the built interface (force-include in pyproject.toml).
python3 - "$wheel" "$pkg" <<'PY'
import sys, zipfile
names = zipfile.ZipFile(sys.argv[1]).namelist()
pkg = sys.argv[2]
assert f"{pkg}/static/index.html" in names, "wheel is missing the built frontend"
assert any(n.startswith(f"{pkg}/static/assets/") for n in names), "wheel has no assets"
assert f"{pkg}/__main__.py" in names
leaked = [n for n in names if n.endswith((".ts", ".tsx"))]
assert not leaked, f"frontend source in the wheel: {leaked}"
print("wheel OK:", sys.argv[1])
PY

stage="$(mktemp -d)/$app"
trap 'rm -rf "$(dirname "$stage")"' EXIT
mkdir -p "$stage/dist"
cp "$wheel" "$stage/dist/"
cp -a "$root/README.md" "$root/LICENSE" "$root/deploy" "$stage/"

# Guard: the tarball is wheel + docs + deploy assets only.
if find "$stage" \( -path '*/web/*' -o -name '*.tsx' -o -name 'vite.config.ts' \
     -o -name node_modules \) -print | grep -q .; then
  echo "frontend source leaked into the tarball" >&2
  exit 1
fi

tar -czf "$out/$app.tar.gz" -C "$(dirname "$stage")" "$app"
cp "$root/deploy/install.sh" "$out/install.sh"
echo "assembled: $out/$app.tar.gz $out/install.sh"
