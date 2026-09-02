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
python3 tools/tailwind/inline_icons.py webapp/templates/dashboard.html

# Compile every stylesheet to a STAGED file first; publish to webapp/static only
# after all of them succeed, so a failed second compile can't leave the committed
# CSS in a mixed-generation state. Temp files are always cleaned up.
trap 'rm -f tools/tailwind/_stage_*.css tools/tailwind/_tw.css' EXIT

build_css() {  # <config> <staged-out>
  npx --yes "tailwindcss@${TW_VERSION}" -c "$1" -i tools/tailwind/input.css -o tools/tailwind/_tw.css --minify
  { cat tools/tailwind/fonts.css; echo; cat tools/tailwind/_tw.css; } > "$2"
  rm -f tools/tailwind/_tw.css
}

echo "==> compiling stylesheets (staged)"
build_css tools/tailwind/tailwind.config.js tools/tailwind/_stage_landing.css
build_css tools/tailwind/verify.config.js  tools/tailwind/_stage_verify.css
build_css tools/tailwind/dashboard.config.js tools/tailwind/_stage_dashboard.css

echo "==> publishing stylesheets (all compiled OK)"
mv tools/tailwind/_stage_landing.css webapp/static/landing.css
mv tools/tailwind/_stage_verify.css  webapp/static/verify.css
mv tools/tailwind/_stage_dashboard.css webapp/static/dashboard.css

echo "==> done"
wc -c webapp/static/landing.css webapp/static/verify.css webapp/static/dashboard.css
