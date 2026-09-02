#!/usr/bin/env bash
# Regenerate the committed landing-page assets.
# Dev-only: requires Node (npx) + python3. The running app needs neither —
# it serves the committed webapp/static/landing.css + webapp/templates/landing.html.
#
#   bash tools/tailwind/build.sh
#
# Rebuilding the HTML from the design also requires the Stitch export at
# tools/tailwind/stitch_source.html (intentionally NOT committed — see README.md).
# If it is absent this script still refetches fonts and recompiles the CSS from the
# committed landing.html, so a clean checkout can reproduce the CSS artifact.
set -euo pipefail
cd "$(dirname "$0")/../.."

TW_VERSION="3.4.17"
SRC="tools/tailwind/stitch_source.html"

echo "==> fetching self-hosted fonts"
python3 tools/tailwind/fetch_fonts.py

if [ -f "$SRC" ]; then
  echo "==> rebuilding landing.html from Stitch source"
  python3 tools/tailwind/build_landing.py
else
  echo "==> $SRC not present — skipping HTML rebuild"
  echo "    (using committed webapp/templates/landing.html; export the Stitch landing"
  echo "     screen to $SRC to regenerate it — see tools/tailwind/README.md)"
fi

echo "==> compiling Tailwind (v${TW_VERSION}) from webapp/templates/landing.html"
npx --yes "tailwindcss@${TW_VERSION}" \
  -c tools/tailwind/tailwind.config.js \
  -i tools/tailwind/input.css \
  -o tools/tailwind/tailwind.out.css \
  --minify

echo "==> assembling webapp/static/landing.css (font faces + compiled utilities)"
{
  cat tools/tailwind/fonts.css
  echo
  cat tools/tailwind/tailwind.out.css
} > webapp/static/landing.css
rm -f tools/tailwind/tailwind.out.css

echo "==> done"
wc -c webapp/static/landing.css
