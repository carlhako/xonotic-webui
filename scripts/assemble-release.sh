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
out="${1:-$root/release}"
mkdir -p "$out"
out="$(cd "$out" && pwd)"

wheel=""
for candidate in "$root"/dist/xonotic_webui-*-py3-none-any.whl; do
  [ -f "$candidate" ] && { wheel="$candidate"; break; }
done
[ -n "$wheel" ] || { echo "no wheel in $root/dist (run: python -m build --wheel)" >&2; exit 1; }

# The wheel must contain the built interface (force-include in pyproject.toml).
python3 - "$wheel" <<'PY'
import sys, zipfile
names = zipfile.ZipFile(sys.argv[1]).namelist()
assert "xonotic_webui/static/index.html" in names, "wheel is missing the built frontend"
assert any(n.startswith("xonotic_webui/static/assets/") for n in names), "wheel has no assets"
assert "xonotic_webui/__main__.py" in names
leaked = [n for n in names if n.endswith((".ts", ".tsx"))]
assert not leaked, f"frontend source in the wheel: {leaked}"
print("wheel OK:", sys.argv[1])
PY

stage="$(mktemp -d)/xonotic-webui"
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

tar -czf "$out/xonotic-webui.tar.gz" -C "$(dirname "$stage")" xonotic-webui
cp "$root/deploy/install.sh" "$out/install.sh"
echo "assembled: $out/xonotic-webui.tar.gz $out/install.sh"
