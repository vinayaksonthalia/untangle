#!/usr/bin/env bash
# Regenerate the committed landing-page assets from source.
# Dev-only: requires Node (npx) + python3. The running app needs neither —
# it serves the committed webapp/static/landing.css and webapp/templates/landing.html.
#
#   bash tools/tailwind/build.sh
#
set -euo pipefail
cd "$(dirname "$0")/../.."

TW_VERSION="3.4.17"

echo "==> fetching self-hosted fonts"
python3 tools/tailwind/fetch_fonts.py

echo "==> building landing.html from Stitch source"
python3 tools/tailwind/build_landing.py

echo "==> compiling Tailwind (v${TW_VERSION})"
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
