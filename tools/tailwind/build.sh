#!/usr/bin/env bash
# Regenerate the committed landing/verify CSS from the committed templates + fonts.
# Dev-only: requires Node (npx) + python3. The running app needs neither.
#
#   bash tools/tailwind/build.sh                 # deterministic: recompile CSS only
#   bash tools/tailwind/build.sh --refresh-fonts # ALSO re-fetch fonts (non-deterministic)
#
# By default this does NOT touch the fonts: the woff2 files and tools/tailwind/fonts.css
# are committed, pinned inputs, so a clean checkout reproduces webapp/static/*.css exactly.
# Font re-fetching hits the live (unversioned) Google Fonts API and is therefore opt-in.
set -euo pipefail
cd "$(dirname "$0")/../.."

TW_VERSION="3.4.17"
SRC="tools/tailwind/stitch_source.html"
REFRESH_FONTS=0
[ "${1:-}" = "--refresh-fonts" ] && REFRESH_FONTS=1

if [ "$REFRESH_FONTS" = "1" ]; then
  echo "==> re-fetching fonts from Google Fonts (non-deterministic; updates committed woff2 + fonts.css)"
  python3 tools/tailwind/fetch_fonts.py
else
  echo "==> using committed fonts (tools/tailwind/fonts.css); pass --refresh-fonts to update them"
  [ -f tools/tailwind/fonts.css ] || { echo "ERROR: tools/tailwind/fonts.css missing; run with --refresh-fonts"; exit 1; }
fi

if [ -f "$SRC" ]; then
  echo "==> rebuilding landing.html from Stitch source"
  python3 tools/tailwind/build_landing.py
else
  echo "==> $SRC not present — skipping landing HTML rebuild (using committed landing.html)"
fi

echo "==> inlining icons in verify.html (idempotent)"
python3 tools/tailwind/inline_icons.py webapp/templates/verify.html

compile() {  # <config> <out-css>
  npx --yes "tailwindcss@${TW_VERSION}" -c "$1" -i tools/tailwind/input.css -o tools/tailwind/_tw.css --minify
  { cat tools/tailwind/fonts.css; echo; cat tools/tailwind/_tw.css; } > "$2"
  rm -f tools/tailwind/_tw.css
}

echo "==> compiling webapp/static/landing.css"
compile tools/tailwind/tailwind.config.js webapp/static/landing.css
echo "==> compiling webapp/static/verify.css"
compile tools/tailwind/verify.config.js webapp/static/verify.css

echo "==> done"
wc -c webapp/static/landing.css webapp/static/verify.css
