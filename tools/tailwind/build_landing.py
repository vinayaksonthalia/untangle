#!/usr/bin/env python3
"""Build webapp/templates/landing.html from the approved Stitch design.

Transforms the exported Stitch mockup into a self-hosted, CSP-safe landing page:
  * drops the mock app-shell (sidebar + fabricated "Audit Officer" persona chrome)
    and gives the page a real top nav + footer;
  * replaces every Material Symbols web-font glyph with an inline SVG
    (currentColor, aria-hidden, sized via 1em so existing text-size classes win);
  * rewrites placeholder CTAs to real application routes;
  * corrects marketing copy to claims the repo can actually back;
  * guards the ambient particle animation behind prefers-reduced-motion.

Source of truth for icon shapes: tools/tailwind/icons/*.svg (Material Symbols,
Apache-2.0). Run from repo root:  python3 tools/tailwind/build_landing.py
"""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = ROOT / "tools" / "tailwind" / "stitch_source.html"
ICON_DIR = ROOT / "tools" / "tailwind" / "icons"
OUT = ROOT / "webapp" / "templates" / "landing.html"

REPO = "https://github.com/vinayaksonthalia/untangle"

# ---------------------------------------------------------------------------
# Icon inlining
# ---------------------------------------------------------------------------
def load_icons() -> dict[str, str]:
    icons: dict[str, str] = {}
    for svg in ICON_DIR.glob("*.svg"):
        text = svg.read_text(encoding="utf-8")
        inner = re.sub(r"^.*?<svg[^>]*>", "", text, flags=re.DOTALL)
        inner = re.sub(r"</svg>\s*$", "", inner, flags=re.DOTALL)
        icons[svg.stem] = inner.strip()
    return icons


ICONS = load_icons()

# <span|div class="... material-symbols-outlined ...">icon_name</span|div>
ICON_TAG_RE = re.compile(
    r'<(?P<tag>span|div)\s+class="(?P<cls>[^"]*material-symbols-outlined[^"]*)"'
    r'(?P<rest>[^>]*)>(?P<name>[a-z_]+)</(?P=tag)>'
)


def inline_icon(m: re.Match) -> str:
    name = m.group("name")
    if name not in ICONS:
        raise SystemExit(f"missing icon svg for {name!r}")
    # keep every class except the web-font marker
    classes = [c for c in m.group("cls").split() if c != "material-symbols-outlined"]
    class_attr = f' class="{" ".join(classes)}"' if classes else ""
    return (
        f'<svg viewBox="0 -960 960 960" width="1em" height="1em" fill="currentColor"'
        f' aria-hidden="true" focusable="false"{class_attr}>{ICONS[name]}</svg>'
    )


# ---------------------------------------------------------------------------
# <button> -> <a href> for real CTAs (matched by the text they contain)
# ---------------------------------------------------------------------------
CTA_HREFS = [
    ("Try with sample data", "/try-sample"),
    ("Upload your files", "/app"),
    ("GENERATE EXPORT", "/app"),
    ("INVESTIGATE", "/try-sample"),
    ("See a live reconciliation", "/try-sample"),
]
BUTTON_RE = re.compile(r"<button\b(?P<attrs>[^>]*)>(?P<inner>.*?)</button>", re.DOTALL)


def buttons_to_links(html: str) -> str:
    def repl(m: re.Match) -> str:
        attrs, inner = m.group("attrs"), m.group("inner")
        for text, href in CTA_HREFS:
            if text in inner:
                # strip type="button" / onclick, keep class + the rest
                cleaned = re.sub(r'\s(?:type|onclick)="[^"]*"', "", attrs)
                extra = "" if "inline-flex" in cleaned or "flex" in cleaned else " inline-flex items-center justify-center"
                cleaned = re.sub(r'class="', f'class="{extra.strip()} ' if extra else 'class="', cleaned, count=1)
                return f'<a href="{href}" role="button"{cleaned}>{inner}</a>'
        return m.group(0)  # leave FAQ accordion buttons untouched

    return BUTTON_RE.sub(repl, html)


# ---------------------------------------------------------------------------
# Copy corrections — only claims the repo can back
# ---------------------------------------------------------------------------
COPY_FIXES = [
    # stale/absolute claims -> honest, non-brittle
    (
        "precision 1.000 · abstains, never guesses · every verdict independently verifiable · 243 tests passing",
        "sealed-benchmark precision ≥ 0.999 · abstains rather than guessing · every verdict independently verifiable",
    ),
    # fabricated "average recovery" -> tie to the labelled example run
    ("AVERAGE RECOVERY", "EXAMPLE RUN · GST RECOVERED"),
    ("₹42k / month", "₹12,450"),
    # label the hero preview as illustrative
    (
        "Live reconciliation — 91 of 103 matched, exceptions surfaced",
        "Example run — 91 of 103 matched, exceptions surfaced",
    ),
]

# section anchors used by the top nav
ANCHOR_FIXES = [
    ("<!-- HOW IT WORKS Section -->\n<section", '<!-- HOW IT WORKS Section -->\n<section id="how"'),
    ("<!-- PRODUCT PROOF Section -->\n<section", '<!-- PRODUCT PROOF Section -->\n<section id="evidence"'),
    ("<!-- FAQ Section -->\n<section", '<!-- FAQ Section -->\n<section id="faq"'),
]


# ---------------------------------------------------------------------------
# Static chrome
# ---------------------------------------------------------------------------
WORDMARK = '<span class="text-audit-blue">un</span><span class="text-on-surface">tangle</span>'

HEAD_STYLE = """
    html, body { margin: 0; padding: 0; }
    body { overscroll-behavior: none; }
    main > :first-child { margin-top: 0 !important; }
    ::-webkit-scrollbar { display: none; }

    @media (prefers-reduced-motion: no-preference) {
      .animate-fade-rise { animation: fadeRise 0.8s cubic-bezier(0.22,1,0.36,1) forwards; opacity: 0; transform: translateY(12px); }
      @keyframes fadeRise { to { opacity: 1; transform: translateY(0); } }
      .delay-0{animation-delay:0ms}.delay-70{animation-delay:70ms}.delay-140{animation-delay:140ms}
      .delay-210{animation-delay:210ms}.delay-280{animation-delay:280ms}.delay-350{animation-delay:350ms}
      .delay-420{animation-delay:420ms}.delay-490{animation-delay:490ms}
    }
    .tooltip-trigger { position: relative; cursor: help; border-bottom: 1px dotted currentColor; }
    .tooltip-trigger:hover::after { content: attr(data-tooltip); position: absolute; bottom: 100%; left: 50%;
      transform: translateX(-50%) translateY(-8px); background:#0f172a; color:#fff; padding:6px 10px;
      border-radius:4px; font-size:12px; white-space:nowrap; z-index:50; pointer-events:none; font-family:'Inter',sans-serif;
      box-shadow:0 4px 6px -1px rgba(0,0,0,.1),0 2px 4px -1px rgba(0,0,0,.06); }
    .tooltip-trigger:hover::before { content:''; position:absolute; bottom:100%; left:50%;
      transform:translateX(-50%) translateY(-2px); border-width:6px 6px 0; border-style:solid;
      border-color:#0f172a transparent transparent transparent; z-index:50; }
    .accordion-content { transition: max-height .4s ease-in-out, opacity .3s ease-in-out, padding .3s ease-in-out;
      max-height:0; opacity:0; overflow:hidden; padding-top:0; padding-bottom:0; }
    .accordion-content.open { max-height:800px; opacity:1; padding-top:1rem; padding-bottom:1.5rem; }
    .accordion-icon { transition: transform .3s ease-in-out; }
    .accordion-icon.open { transform: rotate(180deg); }
    @keyframes dash { to { stroke-dashoffset:-100; } }
    .animate-\\[dash_20s_linear_infinite\\]{animation:dash 20s linear infinite}
    .animate-\\[dash_15s_linear_infinite_reverse\\]{animation:dash 15s linear infinite reverse}
    .perspective-1000{perspective:1000px}
    .rotate-y-\\[-5deg\\]{transform:rotateY(-5deg)}
    .rotate-x-\\[2deg\\]{transform:rotateX(2deg)}
    .hover\\:rotate-y-0:hover{transform:rotateY(0) rotateX(0)}
    :focus-visible { outline: 2px solid #0f172a; outline-offset: 2px; }
"""

NAV = f"""<header class="sticky top-0 z-50 w-full bg-surface-container-lowest/90 backdrop-blur-xl border-b border-outline-variant">
<div class="max-w-[1400px] mx-auto px-container-padding h-16 flex items-center justify-between gap-4">
<a href="/" class="font-headline-md text-headline-md tracking-tight" aria-label="untangle — home">{WORDMARK}</a>
<nav aria-label="Primary" class="hidden md:flex items-center gap-8 font-body-md text-on-surface-variant">
<a class="hover:text-on-surface transition-colors" href="#how">How it works</a>
<a class="hover:text-on-surface transition-colors" href="#evidence">Evidence</a>
<a class="hover:text-on-surface transition-colors" href="#faq">FAQ</a>
<a class="hover:text-on-surface transition-colors" href="/verify">Verify</a>
</nav>
<div class="flex items-center gap-3">
<a href="/app" class="hidden sm:inline-flex h-10 items-center px-4 bg-surface text-primary border border-outline-variant font-data-tabular text-data-tabular rounded hover:bg-surface-container-low transition-colors">Upload files</a>
<a href="/try-sample" class="inline-flex h-10 items-center px-4 bg-primary text-on-primary font-data-tabular text-data-tabular rounded hover:bg-audit-blue transition-colors shadow-sm">Try sample</a>
</div>
</div>
</header>"""

FOOTER = f"""<footer class="w-full bg-surface-container-lowest border-t border-outline-variant py-12">
<div class="max-w-[1400px] mx-auto px-container-padding flex flex-col md:flex-row md:items-start justify-between gap-8">
<div class="max-w-sm">
<div class="font-headline-md text-headline-md tracking-tight mb-2">{WORDMARK}</div>
<p class="font-body-sm text-on-surface-variant">Attribution-first reconciliation for Razorpay settlements. Deterministic verdicts, calibrated abstention, and a close anyone can independently re-verify.</p>
</div>
<nav aria-label="Footer" class="flex flex-col gap-2 font-body-sm text-on-surface-variant">
<a class="hover:text-on-surface transition-colors" target="_blank" rel="noopener noreferrer" href="{REPO}">Source</a>
<a class="hover:text-on-surface transition-colors" target="_blank" rel="noopener noreferrer" href="{REPO}/blob/main/docs/ARCHITECTURE.md">Architecture</a>
<a class="hover:text-on-surface transition-colors" target="_blank" rel="noopener noreferrer" href="{REPO}/blob/main/SECURITY.md">Security</a>
<a class="hover:text-on-surface transition-colors" target="_blank" rel="noopener noreferrer" href="{REPO}/blob/main/LICENSE">License (Apache-2.0)</a>
</nav>
</div>
</footer>"""

PARTICLE_SCRIPT = """<script>
  // Ambient grid dots for the hero background. Disabled under reduced motion.
  document.addEventListener('DOMContentLoaded', () => {
    const container = document.getElementById('particle-canvas-container');
    if (!container) return;
    if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const svgNS = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(svgNS, "svg");
    svg.setAttribute("width", "100%");
    svg.setAttribute("height", "100%");
    svg.style.position = "absolute"; svg.style.top = "0"; svg.style.left = "0";
    const spacing = 40;
    const cols = Math.floor(window.innerWidth / spacing);
    const rows = Math.floor(window.innerHeight / spacing);
    for (let i = 0; i < cols; i++) {
      for (let j = 0; j < rows; j++) {
        if (Math.random() > 0.15) continue;
        const circle = document.createElementNS(svgNS, "circle");
        circle.setAttribute("cx", i * spacing + (Math.random() * 10 - 5));
        circle.setAttribute("cy", j * spacing + (Math.random() * 10 - 5));
        circle.setAttribute("r", "1");
        circle.setAttribute("fill", Math.random() > 0.5 ? '#0f172a' : '#10B981');
        circle.style.opacity = (Math.random() * 0.2 + 0.05).toString();
        const duration = Math.random() * 4 + 2;
        circle.style.transition = `opacity ${duration}s ease-in-out`;
        setInterval(() => {
          circle.style.opacity = circle.style.opacity > 0.2 ? "0.05" : (Math.random() * 0.2 + 0.1).toString();
        }, duration * 1000);
        svg.appendChild(circle);
      }
    }
    container.appendChild(svg);
  });

  // FAQ accordion
  function toggleFaq(btn) {
    const content = btn.nextElementSibling;
    const icon = btn.querySelector('.accordion-icon');
    const willOpen = !content.classList.contains('open');
    document.querySelectorAll('.accordion-content.open').forEach(el => {
      if (el !== content) {
        el.classList.remove('open');
        el.previousElementSibling.querySelector('.accordion-icon').classList.remove('open');
        el.previousElementSibling.setAttribute('aria-expanded', 'false');
      }
    });
    content.classList.toggle('open', willOpen);
    icon.classList.toggle('open', willOpen);
    btn.setAttribute('aria-expanded', willOpen ? 'true' : 'false');
  }
</script>"""


def main() -> int:
    src = SRC.read_text(encoding="utf-8")

    # slice out just the section content (drop the mock sidebar + app header)
    start = src.index("<!-- Interactive Background Particles -->")
    end = src.index("<style>\n  /* Base Tailwind injected via config.")
    sections = src[start:end]
    # drop the stray wrapper close that belonged to the removed flex container
    sections = re.sub(r"</div>\s*$", "", sections.rstrip(), count=1)

    for a, b in ANCHOR_FIXES:
        if a not in sections:
            raise SystemExit(f"anchor marker not found: {a!r}")
        sections = sections.replace(a, b)
    for a, b in COPY_FIXES:
        if a not in sections:
            raise SystemExit(f"copy target not found: {a!r}")
        sections = sections.replace(a, b)

    sections = buttons_to_links(sections)
    sections, n_icons = ICON_TAG_RE.subn(inline_icon, sections)
    if "material-symbols-outlined" in sections:
        raise SystemExit("some Material Symbols glyphs were not inlined")

    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>untangle — attribution-first Razorpay reconciliation</title>
<meta name="description" content="untangle reconciles bank credits to Razorpay settlements to the paise, proves every verdict, abstains rather than guess, and hands you a balanced Tally-ready journal."/>
<link rel="stylesheet" href="/static/landing.css"/>
<style>{HEAD_STYLE}</style>
</head>
<body class="bg-background font-body-md text-on-background">
{NAV}
<main>
<div class="relative overflow-hidden bg-background">
{sections}
</div>
</main>
{FOOTER}
{PARTICLE_SCRIPT}
</body>
</html>
"""

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}  ({len(html)} bytes, {n_icons} icons inlined)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
