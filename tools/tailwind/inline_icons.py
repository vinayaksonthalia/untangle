#!/usr/bin/env python3
"""Replace Material Symbols web-font glyphs with inline SVGs in an HTML file.

Usage:  python3 tools/tailwind/inline_icons.py webapp/templates/verify.html

Rewrites the file in place: every
  <span|div class="... material-symbols-outlined ...">icon_name</span|div>
becomes an inline <svg> (currentColor, aria-hidden, sized via 1em so the existing
text-size classes still control it). Icon geometry comes from tools/tailwind/icons/*.svg
(Material Symbols, Apache-2.0). CSP forbids the web font, so glyphs must be inlined.
"""
from __future__ import annotations

import pathlib
import re
import sys

ICON_DIR = pathlib.Path(__file__).resolve().parent / "icons"

ICON_TAG_RE = re.compile(
    r'<(?P<tag>span|div)\s+class="(?P<cls>[^"]*material-symbols-outlined[^"]*)"'
    r'(?P<rest>[^>]*)>(?P<name>[a-z_]+)</(?P=tag)>'
)


def _load_icons() -> dict[str, str]:
    icons: dict[str, str] = {}
    for svg in ICON_DIR.glob("*.svg"):
        text = svg.read_text(encoding="utf-8")
        inner = re.sub(r"^.*?<svg[^>]*>", "", text, flags=re.DOTALL)
        inner = re.sub(r"</svg>\s*$", "", inner, flags=re.DOTALL)
        icons[svg.stem] = inner.strip()
    return icons


def inline_file(path: pathlib.Path) -> int:
    icons = _load_icons()

    def repl(m: re.Match) -> str:
        name = m.group("name")
        if name not in icons:
            raise SystemExit(f"missing icon svg for {name!r} (add tools/tailwind/icons/{name}.svg)")
        classes = [c for c in m.group("cls").split() if c != "material-symbols-outlined"]
        class_attr = f' class="{" ".join(classes)}"' if classes else ""
        rest = (m.group("rest") or "").strip()  # preserve id=, data-icon=, title=, etc.
        rest = f" {rest}" if rest else ""
        return (
            f'<svg viewBox="0 -960 960 960" width="1em" height="1em" fill="currentColor"'
            f' aria-hidden="true" focusable="false"{class_attr}{rest}>{icons[name]}</svg>'
        )

    html = path.read_text(encoding="utf-8")
    html, n = ICON_TAG_RE.subn(repl, html)
    if "material-symbols-outlined" in html:
        raise SystemExit("some Material Symbols glyphs were not inlined")
    path.write_text(html, encoding="utf-8")
    return n


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        raise SystemExit("usage: inline_icons.py <html-file>")
    path = pathlib.Path(argv[1])
    n = inline_file(path)
    print(f"inlined {n} icons in {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
