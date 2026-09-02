# Landing-page build toolchain (dev-only)

The landing page (`/`) ships as **pre-built, committed artifacts** — the running app
needs no Node, no build step, and no network:

- `webapp/templates/landing.html` — the page (served via `webapp.pages._load_template`)
- `webapp/static/landing.css` — compiled Tailwind + `@font-face` rules
- `webapp/static/fonts/*.woff2` — self-hosted OFL fonts

These committed files are the **source of truth for deploys**. This directory only
holds the tooling to regenerate them.

## Regenerate

```bash
bash tools/tailwind/build.sh      # needs Node (npx) + python3
```

What it does:

1. `fetch_fonts.py` — downloads the latin/latin-ext woff2 subsets → `webapp/static/fonts/`
   and writes `fonts.css` (fails loudly if the set is incomplete).
2. `build_landing.py` — rebuilds `landing.html` from the Stitch export **(only if present)**:
   inlines Material Symbols SVGs, wires CTAs to real routes, applies copy corrections.
3. `tailwindcss` — compiles utilities from `landing.html` → `webapp/static/landing.css`
   (font faces prepended).

## The Stitch design export (`stitch_source.html`)

`build_landing.py` reads `tools/tailwind/stitch_source.html`, the HTML export of the
approved Stitch **landing** screen. It is **intentionally not committed** (it is a
design-tool export, not project source). To rebuild the HTML from the design:

1. Export the Stitch landing screen's HTML.
2. Save it as `tools/tailwind/stitch_source.html`.
3. Run `bash tools/tailwind/build.sh` (or `python3 tools/tailwind/build_landing.py`).

Without it, `build.sh` skips the HTML rebuild and still refetches fonts and recompiles
the CSS from the committed `landing.html`, so the CSS artifact remains reproducible in a
clean checkout. Editing the committed `landing.html` directly is also fine for small
changes — just re-run `build.sh` afterwards to recompile the CSS.

## Licenses

- Fonts: SIL OFL 1.1 — see `webapp/static/fonts/LICENSES.md` + `OFL.txt`.
- Icons: Material Symbols, Apache-2.0 — see `tools/tailwind/icons/LICENSE.md`.
