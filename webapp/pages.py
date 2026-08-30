"""Server-rendered landing + upload pages, in the dashboard's design system."""

from __future__ import annotations

_HEAD = """<!doctype html><html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>{title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,480;9..144,560&family=Inter:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root{{--bg:#f7f7f5;--surface:#fff;--sunken:#fbfbfa;--border:#e6e4df;--border2:#d8d5ce;
--tp:#14140f;--ts:#6b6b62;--tt:#9b9b90;--acc:#2b5edb;--acc-tint:#eaf0fd;--ok:#1b7a4d;--warn:#b4720a;
--disp:'Fraunces',Georgia,serif;--ui:'Inter',-apple-system,'Segoe UI',sans-serif;--mono:'IBM Plex Mono',ui-monospace,monospace;--max:1120px;}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--tp);font-family:var(--ui);-webkit-font-smoothing:antialiased;font-size:15px;line-height:1.55}}
a{{color:var(--acc);text-decoration:none}}a:hover{{text-decoration:underline}}
.topbar{{position:sticky;top:0;z-index:5;background:rgba(247,247,245,.86);backdrop-filter:blur(8px);border-bottom:1px solid var(--border);height:56px;display:flex;align-items:center}}
.topbar .in{{max-width:var(--max);margin:0 auto;padding:0 40px;width:100%;display:flex;align-items:center;gap:16px}}
.logo{{font-family:var(--disp);font-weight:560;font-size:19px;letter-spacing:-.01em;font-optical-sizing:auto;color:var(--tp)}}
.logo b{{color:var(--acc);font-weight:560}}
.nav{{margin-left:auto;display:flex;gap:22px;font-size:13.5px}}.nav a{{color:var(--ts)}}
.wrap{{max-width:var(--max);margin:0 auto;padding:72px 40px 90px}}
.eyebrow{{font-weight:600;font-size:11px;letter-spacing:.09em;text-transform:uppercase;color:var(--acc);margin:0 0 18px}}
h1{{font-family:var(--disp);font-weight:480;font-size:50px;line-height:1.05;letter-spacing:-.02em;margin:0;max-width:16ch;font-optical-sizing:auto}}
.sub{{font-size:18px;color:var(--ts);max-width:60ch;margin:22px 0 34px;line-height:1.5}}
.cta{{display:inline-flex;align-items:center;gap:8px;font-weight:500;font-size:15px;padding:12px 22px;border-radius:9px;border:1px solid transparent}}
.cta.primary{{background:var(--acc);color:#fff}}.cta.primary:hover{{background:#2450c0;text-decoration:none}}
.cta.ghost{{border-color:var(--border2);color:var(--tp);background:var(--surface)}}.cta.ghost:hover{{border-color:var(--tp);text-decoration:none}}
.ctarow{{display:flex;gap:14px;flex-wrap:wrap;align-items:center}}
.free{{color:var(--tt);font-size:13px;margin-left:4px}}
.props{{display:grid;grid-template-columns:repeat(3,1fr);gap:20px;margin-top:80px}}
.prop{{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:26px}}
.prop h3{{font-family:var(--disp);font-weight:480;font-size:19px;margin:0 0 10px;letter-spacing:-.01em}}
.prop p{{color:var(--ts);font-size:14px;margin:0;line-height:1.55}}
.section-h{{font-family:var(--disp);font-weight:480;font-size:28px;letter-spacing:-.01em;margin:96px 0 6px;font-optical-sizing:auto}}
.section-s{{color:var(--ts);margin:0 0 30px}}
.steps{{display:grid;grid-template-columns:repeat(3,1fr);gap:20px}}
.step{{border-top:2px solid var(--tp);padding-top:16px}}
.step .n{{font-family:var(--mono);font-size:12px;color:var(--acc);font-weight:500}}
.step h4{{font-size:15px;margin:8px 0 6px}}.step p{{color:var(--ts);font-size:13.5px;margin:0}}
.who{{display:grid;grid-template-columns:repeat(3,1fr);gap:20px}}
.wc{{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:22px}}
.wc .k{{font-weight:600;font-size:13px;letter-spacing:.04em;text-transform:uppercase;color:var(--ts)}}
.wc p{{color:var(--ts);font-size:13.5px;margin:10px 0 0}}
.privacy{{margin-top:80px;background:var(--surface);border:1px solid var(--border);border-left:3px solid var(--ok);border-radius:12px;padding:24px 26px}}
.privacy h3{{font-family:var(--disp);font-weight:480;font-size:19px;margin:0 0 8px}}
.privacy p{{color:var(--ts);font-size:14px;margin:0}}
footer{{max-width:var(--max);margin:70px auto 0;padding:22px 40px 40px;border-top:1px solid var(--border);font-family:var(--mono);font-size:12px;color:var(--tt);display:flex;gap:24px;flex-wrap:wrap}}
footer b{{color:var(--ts);font-weight:500}}
/* upload */
.up{{max-width:960px}}
.drops{{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin:30px 0 0}}
.drop{{display:block;text-align:left;position:relative;cursor:pointer;background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:20px 20px 22px;
  box-shadow:0 1px 0 rgba(20,20,15,.02),0 14px 32px -28px rgba(20,20,15,.30);transition:border-color .15s,box-shadow .15s,background .15s,transform .15s}}
.drop:hover{{border-color:var(--border2);box-shadow:0 1px 0 rgba(20,20,15,.03),0 18px 36px -24px rgba(20,20,15,.34);transform:translateY(-1px)}}
.drop.drag{{border-color:var(--acc);background:var(--acc-tint);box-shadow:0 0 0 3px rgba(43,94,219,.12)}}
.drop.ok{{border-color:var(--ok);background:#f5faf7}}
.drop .num{{display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;border-radius:50%;background:var(--acc-tint);color:var(--acc);font-family:var(--mono);font-size:11px;font-weight:500}}
.drop.ok .num{{background:#dbf0e4;color:var(--ok)}}
.drop h4{{font-size:14.5px;margin:12px 0 3px}}.drop .hint{{color:var(--tt);font-size:12px;margin:0 0 12px}}
.drop .cols{{font-family:var(--mono);font-size:10.5px;color:var(--ts);background:var(--sunken);border:1px solid var(--border);border-radius:6px;padding:6px 8px;display:block;margin-bottom:14px;line-height:1.5;word-break:break-word}}
.drop input[type=file]{{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0 0 0 0);border:0}}
.pick{{display:inline-flex;align-items:center;gap:7px;font-size:12.5px;font-weight:500;color:var(--tp);background:var(--surface);border:1px solid var(--border2);border-radius:8px;padding:8px 13px}}
.drop:hover .pick{{border-color:var(--tp)}}
.drop.ok .pick,.drop.ok .droptip{{display:none}}
.droptip{{font-size:11.5px;color:var(--tt);margin-left:10px}}
.drop .status{{display:none;align-items:flex-start;gap:7px;font-size:12.5px;color:var(--ok);margin-top:14px;font-weight:500;word-break:break-all;line-height:1.4}}
.drop.ok .status{{display:flex}}
.note{{background:var(--sunken);border:1px solid var(--border);border-radius:10px;padding:16px 18px;color:var(--ts);font-size:13px;margin:22px 0}}
.note b{{color:var(--tp)}}
.submit{{display:flex;gap:14px;align-items:center;flex-wrap:wrap;margin-top:22px}}
.roadmap{{display:grid;grid-template-columns:repeat(2,1fr);gap:16px;margin-top:20px}}
.rc{{border:1px solid var(--border);border-radius:12px;padding:18px;color:var(--ts);font-size:13px;background:var(--surface)}}
.rc .t{{font-weight:600;color:var(--tp);font-size:13px}}.rc .soon{{font-family:var(--mono);font-size:10px;color:var(--warn);text-transform:uppercase;letter-spacing:.06em;margin-left:6px}}
@media(max-width:840px){{.wrap,.topbar .in,footer{{padding-left:22px;padding-right:22px}}h1{{font-size:36px}}
.props,.steps,.who,.drops,.roadmap{{grid-template-columns:1fr}}}}
</style></head><body>
<div class="topbar"><div class="in"><a class="logo" href="/">un<b>tangle</b></a>
<span class="nav"><a href="/app">Reconcile</a><a href="/try-sample">Sample</a><a href="/api/docs">API</a>
<a href="https://github.com/vinayaksonthalia/untangle">Source</a></span></div></div>"""

_FOOT = """<footer><span><b>untangle</b> · multi-rail settlement reconciliation</span>
<span>processed in memory · <b>nothing stored</b></span><span>open source · deterministic</span></footer>
</body></html>"""


_LANDING_CSS = """<style>
.hero{display:grid;grid-template-columns:1.05fr .95fr;gap:56px;align-items:center;margin-top:8px}
.hero-copy h1{max-width:15ch}
.badge{display:inline-flex;align-items:center;gap:8px;background:var(--surface);border:1px solid var(--border);border-radius:999px;padding:5px 13px;font-size:12.5px;color:var(--ts);margin-bottom:22px}
.badge .dot{width:7px;height:7px;border-radius:50%;background:var(--ok);box-shadow:0 0 0 3px rgba(27,122,77,.14)}
/* hero sorting figure */
.fig{background:var(--surface);border:1px solid var(--border);border-radius:16px;padding:22px 20px;box-shadow:0 1px 0 rgba(20,20,15,.02),0 18px 40px -28px rgba(20,20,15,.22)}
.fig-h{font-family:var(--mono);font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--tt);margin:0 0 14px;display:flex;justify-content:space-between}
.svgwrap{width:100%}
.fig-cap{font-size:12px;color:var(--ts);margin:14px 2px 0;line-height:1.5}
.fig-cap b{color:var(--tp);font-weight:600}
/* stat band */
.proof{margin-top:96px;background:#101014;border-radius:16px;padding:38px 40px;color:#e9e9e6}
.proof .lab{font-family:var(--mono);font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:#8a8a86;margin:0 0 6px}
.proof h2{font-family:var(--disp);font-weight:480;font-size:26px;color:#fff;margin:0 0 26px;letter-spacing:-.01em}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}
.stat{background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.09);border-radius:11px;padding:18px 18px}
.stat .v{font-family:var(--disp);font-size:32px;font-weight:480;letter-spacing:-.02em;color:#fff;line-height:1}
.stat .v.warn{color:#f0b357}.stat .v.ok{color:#57c98a}
.stat .k{font-size:12.5px;color:#b7b7b2;margin-top:9px;line-height:1.4}
.proof .fine{font-family:var(--mono);font-size:11px;color:#8a8a86;margin:22px 0 0;line-height:1.6}
.proof .fine b{color:#c9c9c4;font-weight:500}
/* decoy trap */
.trap{margin-top:96px;display:grid;grid-template-columns:.9fr 1.1fr;gap:44px;align-items:center}
.trap .k{font-family:var(--mono);font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--warn);margin:0 0 12px}
.trap h2{font-family:var(--disp);font-weight:480;font-size:30px;letter-spacing:-.01em;margin:0 0 14px;line-height:1.12}
.trap p{color:var(--ts);font-size:15px;margin:0 0 12px;line-height:1.6}
.decoy{background:var(--surface);border:1px solid var(--border);border-radius:14px;overflow:hidden;font-family:var(--mono)}
.decoy .row{display:flex;justify-content:space-between;align-items:baseline;padding:16px 20px;border-bottom:1px solid var(--border)}
.decoy .amt{font-size:20px;color:var(--tp);font-weight:500}
.decoy .narr{font-size:12px;color:var(--ts);padding:12px 20px;background:var(--sunken);border-bottom:1px solid var(--border);word-break:break-all}
.decoy .sig{padding:14px 20px;display:grid;gap:9px}
.sigline{display:flex;align-items:center;gap:10px;font-size:12.5px}
.sigline .m{width:15px;text-align:center;font-weight:700}
.sigline .m.no{color:#c0392b}.sigline .m.yes{color:var(--ok)}
.sigline span{color:var(--ts)}
.verdict{padding:15px 20px;background:#fbf6ec;border-top:1px solid var(--border);font-family:var(--ui);font-size:13.5px;color:var(--warn)}
.verdict b{color:#9a5f08}
/* comparison */
.vs-wrap{margin-top:26px;overflow-x:auto;-webkit-overflow-scrolling:touch;border:1px solid var(--border);border-radius:12px}
.vs{width:100%;border-collapse:collapse;font-size:14px;background:var(--surface);min-width:520px}
.vs th,.vs td{text-align:left;padding:14px 18px;border-bottom:1px solid var(--border);vertical-align:top}
.vs thead th{font-family:var(--mono);font-size:11px;letter-spacing:.05em;text-transform:uppercase;color:var(--ts);font-weight:500;background:var(--sunken)}
.vs thead th:last-child{color:var(--acc)}
.vs td:first-child{color:var(--ts);width:32%}
.vs td.them{color:var(--ts)}
.vs td.us{color:var(--tp);font-weight:500}
.vs tr:last-child td{border-bottom:none}
/* faq */
.faq{margin-top:36px;display:grid;gap:0;border-top:1px solid var(--border)}
.faq details{border-bottom:1px solid var(--border);padding:2px 0}
.faq summary{cursor:pointer;list-style:none;padding:18px 2px;font-weight:500;font-size:15.5px;color:var(--tp);display:flex;justify-content:space-between;align-items:center}
.faq summary::-webkit-details-marker{display:none}
.faq summary::after{content:'+';font-family:var(--mono);color:var(--tt);font-size:18px}
.faq details[open] summary::after{content:'–'}
.faq p{color:var(--ts);font-size:14px;margin:0 2px 18px;max-width:74ch;line-height:1.6}
/* hero figure — the agent sorting, on a gentle loop (reduced-motion safe) */
.hc{opacity:0;animation:hcin .5s ease forwards;animation-delay:calc(var(--i)*.55s + .2s)}
.hw{stroke-dasharray:1;stroke-dashoffset:1;animation:hwdraw 9s ease-in-out infinite;animation-delay:calc(var(--i)*.55s)}
@keyframes hcin{to{opacity:1}}
@keyframes hwdraw{0%{stroke-dashoffset:1}18%{stroke-dashoffset:0}86%{stroke-dashoffset:0}94%{stroke-dashoffset:1}100%{stroke-dashoffset:1}}
/* abstained tie keeps its dashed look ("4 3") — only pulses, never redrawn */
.hw-ab{animation:abpulse 2.2s ease-in-out infinite}
@keyframes abpulse{0%,100%{opacity:.5}50%{opacity:1}}
@media(prefers-reduced-motion:reduce){
  .hc{opacity:1;animation:none}
  .hw{stroke-dashoffset:0;animation:none}
  .hw-ab{animation:none;opacity:1}
}
/* hero hint + bring-your-own-data */
.herohint{margin:18px 0 0;font-size:13px;color:var(--tt)}
.herohint a{font-weight:500}
.bring{margin-top:96px;background:var(--sunken);border:1px solid var(--border);border-radius:16px;padding:38px 36px;scroll-margin-top:72px}
.bring-head{max-width:66ch}
.bring-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:18px;margin-top:26px}
.bfile{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:20px 20px 18px;position:relative}
.bfile .bnum{font-family:var(--mono);font-size:11px;color:var(--acc);font-weight:500;letter-spacing:.06em}
.bfile h4{font-size:15px;margin:8px 0 6px}
.bfile .bsrc{color:var(--ts);font-size:13px;margin:0 0 12px;line-height:1.5}
.bfile .bcols{font-family:var(--mono);font-size:10.5px;color:var(--ts);background:var(--sunken);border:1px solid var(--border);border-radius:6px;padding:6px 8px;line-height:1.5}
/* final cta */
.finalcta{margin-top:96px;text-align:center;background:var(--surface);border:1px solid var(--border);border-radius:16px;padding:52px 30px}
.finalcta h2{font-family:var(--disp);font-weight:480;font-size:32px;letter-spacing:-.01em;margin:0 0 10px}
.finalcta p{color:var(--ts);margin:0 auto 26px;max-width:52ch}
@media(max-width:840px){.hero{grid-template-columns:1fr;gap:34px}.trap{grid-template-columns:1fr;gap:26px}
.stats{grid-template-columns:repeat(2,1fr)}.hero-copy h1{max-width:none}.bring-grid{grid-template-columns:1fr}.bring{padding:28px 22px}}
@media(max-width:520px){.stats{grid-template-columns:1fr}.proof{padding:28px 22px}.vs th,.vs td{padding:12px 13px}}
</style>"""

# Inline SVG: commingled credits on the left sort into rails on the right; one abstains.
_HERO_SVG = """<svg class="svgwrap" viewBox="0 0 440 300" role="img"
  aria-label="Bank credits sorted into rails, with one credit abstained for review" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <marker id="ah" markerWidth="7" markerHeight="7" refX="5" refY="3" orient="auto">
      <path d="M0,0 L6,3 L0,6 Z" fill="#c9c7c0"/></marker>
  </defs>
  <text x="14" y="20" font-family="'IBM Plex Mono',monospace" font-size="10" fill="#9b9b90" letter-spacing="1">BANK CREDITS</text>
  <text x="300" y="20" font-family="'IBM Plex Mono',monospace" font-size="10" fill="#9b9b90" letter-spacing="1">ATTRIBUTED RAIL</text>
  <!-- credit chips -->
  <g font-family="'IBM Plex Mono',monospace" font-size="11" fill="#14140f">
    <g class="hc" style="--i:0"><rect x="12" y="34" width="118" height="30" rx="7" fill="#fff" stroke="#e6e4df"/><text x="24" y="53">₹2,14,320</text></g>
    <g class="hc" style="--i:1"><rect x="12" y="78" width="118" height="30" rx="7" fill="#fff" stroke="#e6e4df"/><text x="24" y="97">₹  88,400</text></g>
    <g class="hc" style="--i:2"><rect x="12" y="122" width="118" height="30" rx="7" fill="#fff" stroke="#e6e4df"/><text x="24" y="141">₹  12,500</text></g>
    <g class="hc" style="--i:3"><rect x="12" y="166" width="118" height="30" rx="7" fill="#fff" stroke="#e6e4df"/><text x="24" y="185">₹  49,999</text></g>
    <g class="hc" style="--i:4"><rect x="12" y="210" width="118" height="30" rx="7" fill="#fff" stroke="#e6e4df"/><text x="24" y="229">₹  31,050</text></g>
  </g>
  <!-- connectors (draw in sequence) -->
  <g fill="none" stroke="#c9c7c0" stroke-width="1.4" marker-end="url(#ah)">
    <path class="hw" style="--i:0" pathLength="1" d="M132,49 C210,49 214,52 296,52"/>
    <path class="hw" style="--i:1" pathLength="1" d="M132,93 C210,93 214,52 296,56" opacity=".85"/>
    <path class="hw" style="--i:2" pathLength="1" d="M132,137 C210,137 214,100 296,100"/>
    <path class="hw" style="--i:3" pathLength="1" d="M132,180 C210,180 214,148 296,148"/>
    <path class="hw-ab" style="--i:4" d="M132,224 C214,224 220,210 296,210" stroke="#e0b877" stroke-dasharray="4 3"/>
  </g>
  <!-- rail pills -->
  <g font-family="Inter,sans-serif" font-size="11.5">
    <rect x="296" y="40" width="132" height="30" rx="7" fill="#eaf0fd" stroke="#cddcfb"/>
    <circle cx="311" cy="55" r="4" fill="#2b5edb"/><text x="322" y="59" fill="#1e3a8a">Razorpay ×2</text>
    <rect x="296" y="86" width="132" height="30" rx="7" fill="#fff" stroke="#e6e4df"/>
    <circle cx="311" cy="101" r="4" fill="#6b6b62"/><text x="322" y="105" fill="#4b4b45">Other gateway</text>
    <rect x="296" y="132" width="132" height="30" rx="7" fill="#fff" stroke="#e6e4df"/>
    <circle cx="311" cy="147" r="4" fill="#1b7a4d"/><text x="322" y="151" fill="#4b4b45">Direct UPI</text>
    <rect x="296" y="196" width="132" height="30" rx="7" fill="#fbf6ec" stroke="#ecd9b0"/>
    <circle cx="311" cy="211" r="4" fill="#b4720a"/><text x="322" y="215" fill="#9a5f08">Abstained · review</text>
  </g>
</svg>"""


def landing_page() -> str:
    return _HEAD.format(title="untangle — know exactly what every bank credit is") + _LANDING_CSS + """
<div class="wrap">
  <div class="hero">
    <div class="hero-copy">
      <span class="badge"><span class="dot"></span>Precision-first · abstains rather than mislabel</span>
      <h1>Know exactly what every bank credit is.</h1>
      <p class="sub">Settlements, a second gateway, direct UPI, COD remittances, the odd personal transfer — all
      landing in one current account. untangle ties every bank credit to its source rail <b>with evidence</b>,
      reconciles the Razorpay slice to the paise, and recovers the GST on gateway fees. When the proof is
      weak, it says so — it never force-books a guess.</p>
      <div class="ctarow">
        <a class="cta primary" href="/app">Reconcile your files →</a>
        <a class="cta ghost" href="/try-sample">See it on sample data</a>
        <span class="free">free · no signup · nothing stored</span>
      </div>
      <p class="herohint">Bring three exports — bank statement, Razorpay settlement report, order ledger.
      <a href="#bring">What to bring &amp; where to get it ↓</a></p>
    </div>
    <div class="fig">
      <div class="fig-h"><span>one current account</span><span>five rails + review</span></div>
      """ + _HERO_SVG + """
      <p class="fig-cap">Two credits carry a settlement UTR that ties back to the recon report → <b>Razorpay</b>.
      One looks like Razorpay but has no hard tie → <b>abstained</b>, not guessed.</p>
    </div>
  </div>

  <div class="props">
    <div class="prop"><h3>Settled ≠ received. Prove it.</h3>
      <p>Razorpay says an amount settled; your bank shows credits that don't say what they are. untangle ties
      every settlement UTR to a bank credit and reconciles to the paise — and tells you exactly which rupees
      it <i>can't</i> explain.</p></div>
    <div class="prop"><h3>Reclaim the GST on gateway fees.</h3>
      <p>Every settlement silently deducts a fee plus 18% GST. That GST is input tax credit you can claim — if
      you can produce the per-transaction numbers. untangle totals it from Razorpay's own tax figures and gives
      your CA a traceable schedule.</p></div>
    <div class="prop"><h3>It says “I don't know”, not a guess.</h3>
      <p>Every match shows its evidence. When evidence is weak, the credit goes to an exception queue with a
      suggested action — never silently mis-booked. A wrong “this is Razorpay's” corrupts your books; we abstain.</p></div>
  </div>

  <!-- BRING YOUR OWN DATA -->
  <div id="bring" class="bring">
    <div class="bring-head">
      <p class="eyebrow">Run it on your own books</p>
      <h2 class="section-h" style="margin:0">Three exports in. A reconciled verdict out.</h2>
      <p class="section-s">No account, no integration, no signup. Export three files you already have and
      drop them in — untangle reads them in a per-request temporary directory, shows you the answer, and
      deletes them the moment the report renders. Nothing is persisted.</p>
    </div>
    <div class="bring-grid">
      <div class="bfile">
        <div class="bnum">01</div>
        <h4>Bank statement</h4>
        <p class="bsrc">Your netbanking → download statement as <b>CSV</b>.</p>
        <div class="bcols">value_date · narration · credit · debit</div>
      </div>
      <div class="bfile">
        <div class="bnum">02</div>
        <h4>Razorpay settlement report</h4>
        <p class="bsrc">Razorpay Dashboard → <b>Settlements → Reports</b> → export as <b>JSON</b>.</p>
        <div class="bcols">entity_id · type · amount · fee · tax · settlement_utr</div>
      </div>
      <div class="bfile">
        <div class="bnum">03</div>
        <h4>Order ledger</h4>
        <p class="bsrc">Your orders/admin export (CSV) — the list of what you sold.</p>
        <div class="bcols">order_id · amount_paise · status</div>
      </div>
    </div>
    <div class="ctarow" style="margin-top:26px">
      <a class="cta primary" href="/app">Upload your three files →</a>
      <a class="cta ghost" href="/try-sample">Not ready? Watch it on sample data</a>
      <span class="free">Bank statement &amp; ledger as CSV, Razorpay report as JSON · PDF refused on purpose (it gets money wrong) · max 15 MB each</span>
    </div>
  </div>

  <!-- PROOF -->
  <div class="proof">
    <p class="lab">Measured on the sealed, generator-blind benchmark</p>
    <h2>The number that matters isn't how much it matches. It's how rarely it's wrong.</h2>
    <div class="stats">
      <div class="stat"><div class="v ok">1.000</div><div class="k">Razorpay attribution precision — zero false “this is Razorpay's”</div></div>
      <div class="stat"><div class="v ok">0</div><div class="k">Decoy false-positives, across 173 look-alike non-Razorpay credits</div></div>
      <div class="stat"><div class="v">0.91</div><div class="k">Recall on true Razorpay credits — including split legs recovered by provable set-sum; the rest abstain, never guessed</div></div>
      <div class="stat"><div class="v warn">±₹0</div><div class="k">residual on the proven Razorpay slice — every <i>reconciled</i> credit balances to the paise; unresolved credits are surfaced, not forced</div></div>
    </div>
    <p class="fine"><b>Honest scope.</b> These are measured on a labelled, adversarial holdout generated by a
    process the engine never imports (n≈294, 14 narration-corruption modes) — <b>not</b> a claim about every
    real-world statement. On your unlabelled upload we show attributed-vs-abstained counts and a real coverage
    curve, and never assert a precision we cannot measure.</p>
  </div>

  <!-- DECOY TRAP -->
  <div class="trap">
    <div>
      <p class="k">The trap everyone else walks into</p>
      <h2>A credit that looks like Razorpay isn't proof it is.</h2>
      <p>The naive approach matches on brand words and a round amount. But a competitor payout, a refund, or a
      personal transfer can carry the word “razorpay” in the narration and happen to equal a settlement total.</p>
      <p>untangle refuses to call it Razorpay on resemblance. It needs a real <b>tie</b> back to the settlement
      report — an exact UTR, a corroborated UTR suffix, a bounded set-sum of settlement nets, or an amount that
      <i>uniquely</i> matches one settlement net. A brand word, or an amount that merely collides with a total,
      never decides on its own. That one rule is the difference between a clean ledger and a corrupted one.</p>
    </div>
    <div class="decoy">
      <div class="row"><span class="amt">₹31,050.00</span><span style="font-size:11px;color:#9b9b90">14 Jun · credit</span></div>
      <div class="narr">NEFT-AXISP0034192-RAZORPAY-FUNDING-PARTNER-DISBURSAL</div>
      <div class="sig">
        <div class="sigline"><span class="m yes">✓</span><span>brand word “razorpay” present</span></div>
        <div class="sigline"><span class="m yes">✓</span><span>amount equals a settlement total (to the paise)</span></div>
        <div class="sigline"><span class="m no">✗</span><span>no settlement UTR tie in the recon report</span></div>
        <div class="sigline"><span class="m no">✗</span><span>no bounded set-sum of settlement nets</span></div>
      </div>
      <div class="verdict"><b>Verdict: abstained.</b> Brand + amount are coincidental signals, not proof.
      Surfaced for review — not booked as Razorpay.</div>
    </div>
  </div>

  <!-- VS -->
  <h2 class="section-h">Not a matcher. An attributor that knows when to stop.</h2>
  <p class="section-s">Most reconciliation tools answer “does line X match row Y?”. untangle answers “whose money is this — and can I prove it?”.</p>
  <div class="vs-wrap"><table class="vs">
    <thead><tr><th>&nbsp;</th><th>A naive matcher</th><th>untangle</th></tr></thead>
    <tbody>
      <tr><td>Core question</td><td class="them">Does this credit match a settlement?</td><td class="us">Which rail is this credit from — with evidence?</td></tr>
      <tr><td>Commingled rails</td><td class="them">Assumes every credit is a settlement</td><td class="us">Sorts across Razorpay, other gateways, UPI, COD, unrelated</td></tr>
      <tr><td>Weak evidence</td><td class="them">Guesses the closest match</td><td class="us">Abstains into a reasoned review queue</td></tr>
      <tr><td>Look-alike decoys</td><td class="them">Books them on brand + amount</td><td class="us">Requires a hard settlement tie; refuses resemblance</td></tr>
      <tr><td>How you trust it</td><td class="them">A confidence score</td><td class="us">Per-credit evidence trail + a measured false-positive rate</td></tr>
      <tr><td>Fee-GST (ITC)</td><td class="them">Out of scope</td><td class="us">Traceable input-tax-credit schedule from Razorpay's own figures</td></tr>
    </tbody>
  </table></div>

  <section class="bb-section" aria-labelledby="bb-title">
  <style>
    .bb-section {
      padding: 72px 0;
      color: var(--tp);
      font-family: var(--ui);
    }

    .bb-header {
      margin-bottom: 24px;
    }

    .bb-header .section-h,
    .bb-header .section-s {
      margin-left: 0;
      margin-right: 0;
    }

    .bb-header .section-h {
      margin-top: 0;
      margin-bottom: 6px;
    }

    .bb-header .section-s {
      margin-top: 0;
      margin-bottom: 0;
    }

    .bb-table-wrap {
      overflow-x: auto;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--surface);
      -webkit-overflow-scrolling: touch;
    }

    .bb-table {
      width: 100%;
      min-width: 880px;
      border-collapse: collapse;
      table-layout: fixed;
      font-size: 14px;
      line-height: 1.45;
    }

    .bb-table th,
    .bb-table td {
      padding: 16px 18px;
      text-align: left;
      vertical-align: top;
      border-bottom: 1px solid var(--border);
    }

    .bb-table th {
      color: var(--ts);
      background: var(--sunken);
      font-family: var(--mono);
      font-size: 11px;
      font-weight: 600;
      letter-spacing: 0;
      text-transform: uppercase;
    }

    .bb-table th:first-child {
      width: 21%;
    }

    .bb-table th:nth-child(2),
    .bb-table th:nth-child(3) {
      width: 11%;
    }

    .bb-table th:nth-child(4) {
      width: 25%;
    }

    .bb-table th:nth-child(5) {
      width: 32%;
    }

    .bb-table tbody tr:last-child td {
      border-bottom: 0;
    }

    .bb-table tbody tr:hover {
      background: var(--sunken);
    }

    .bb-method {
      display: block;
      margin-bottom: 3px;
      color: var(--tp);
      font-weight: 700;
    }

    .bb-method-note {
      display: block;
      color: var(--ts);
      font-size: 12px;
    }

    .bb-metric {
      display: block;
      color: var(--tp);
      font-family: var(--mono);
      font-size: 17px;
      font-weight: 600;
      white-space: nowrap;
    }

    .bb-fail {
      color: var(--warn);
      font-weight: 700;
    }

    .bb-pass {
      color: var(--ok);
      font-weight: 700;
    }

    .bb-untangle-row {
      background: color-mix(in srgb, var(--ok) 5%, var(--surface));
    }

    .bb-untangle-row:hover {
      background: color-mix(in srgb, var(--ok) 8%, var(--surface)) !important;
    }

    .bb-untangle-row .bb-method {
      color: var(--ok);
    }

    .bb-detail {
      display: block;
      margin-top: 3px;
      color: var(--ts);
      font-size: 12px;
    }

    .bb-close {
      margin: 20px 0 0;
      max-width: 820px;
      font-family: var(--disp);
      font-size: 20px;
      line-height: 1.4;
      letter-spacing: 0;
    }

    .bb-close strong {
      color: var(--ok);
      font-weight: 600;
    }

    .bb-source {
      margin: 14px 0 0;
      max-width: 820px;
      font-size: 12px;
      color: var(--tt);
      line-height: 1.55;
    }
    .bb-source code {
      font-family: var(--mono);
      font-size: 11px;
      color: var(--ts);
    }

    @media (max-width: 640px) {
      .bb-section {
        padding: 52px 0;
      }

      .bb-table th,
      .bb-table td {
        padding: 14px;
      }

      .bb-close {
        font-size: 18px;
      }
    }
  </style>

  <header class="bb-header">
    <h2 class="section-h" id="bb-title">Baseline Battle</h2>
    <p class="section-s">Measured on 294 lines, with razorpay_settlement as the positive class.</p>
  </header>

  <div class="bb-table-wrap">
    <table class="bb-table">
      <thead>
        <tr>
          <th scope="col">Matcher</th>
          <th scope="col">Precision</th>
          <th scope="col">Recall</th>
          <th scope="col">Fooled by</th>
          <th scope="col">Blind to</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>
            <span class="bb-method">Brand-word match</span>
            <span class="bb-method-note">One recognizable name</span>
          </td>
          <td><span class="bb-metric">83%</span></td>
          <td><span class="bb-metric">86%</span></td>
          <td>
            <span class="bb-fail">100% false-positives</span>
            <span class="bb-detail">RAZORPAYX PAYOUTS vendor refunds</span>
          </td>
          <td>
            <span class="bb-fail">0% recall</span>
            <span class="bb-detail">Brand-less real settlements</span>
          </td>
        </tr>

        <tr>
          <td>
            <span class="bb-method">Amount + date match</span>
            <span class="bb-method-note">One coincident pair</span>
          </td>
          <td><span class="bb-metric">84%</span></td>
          <td><span class="bb-metric">80%</span></td>
          <td>
            <span class="bb-fail">81% false-positives</span>
            <span class="bb-detail">Coincidental amount collisions</span>
          </td>
          <td>
            <span class="bb-fail">0% recall</span>
            <span class="bb-detail">Split, merge, and carry-forward settlements</span>
          </td>
        </tr>

        <tr>
          <td>
            <span class="bb-method">Clean-UTR match</span>
            <span class="bb-method-note">One pristine identifier</span>
          </td>
          <td><span class="bb-metric">100%</span></td>
          <td><span class="bb-metric bb-fail">52%</span></td>
          <td>
            <span class="bb-detail">Precise when the key survives intact</span>
          </td>
          <td>
            <span class="bb-fail">0% recall</span>
            <span class="bb-detail">Mangled, prefix-destroyed, or absent UTRs</span>
          </td>
        </tr>

        <tr class="bb-untangle-row">
          <td>
            <span class="bb-method">untangle</span>
            <span class="bb-method-note">Tiered evidence + calibrated abstention</span>
          </td>
          <td><span class="bb-metric bb-pass">1.000</span></td>
          <td><span class="bb-metric bb-pass">0.91</span></td>
          <td>
            <span class="bb-pass">0 decoy false-positives</span>
            <span class="bb-detail">Look-alikes do not create a tie</span>
          </td>
          <td>
            <span class="bb-pass">Abstains instead of guessing</span>
            <span class="bb-detail">Uncertain cases stay explicit</span>
          </td>
        </tr>
      </tbody>
    </table>
  </div>

  <p class="bb-close">Every shortcut is fooled by the trap it can't see. <strong>untangle needs a real tie, or it says so.</strong></p>
  <p class="bb-source">Every figure above is measured on the same labelled 294-line benchmark by <code>generator/difficulty_probe.py</code> — the naive baselines and untangle scored against the identical blind ground truth. Reproduce with <code>python -m generator.difficulty_probe</code>.</p>
</section>

  <h2 class="section-h">How it works</h2>
  <p class="section-s">Three files in, a paise-exact verdict out. No account, no storage.</p>
  <div class="steps">
    <div class="step"><div class="n">01</div><h4>Export three files</h4><p>Your bank statement (CSV from netbanking),
      your Razorpay settlement report (Dashboard → Settlements → Reports), your order list.</p></div>
    <div class="step"><div class="n">02</div><h4>Drop them here</h4><p>Processed in memory and discarded after.
      No account, no database, nothing persisted (any temp file is deleted right after the run).</p></div>
    <div class="step"><div class="n">03</div><h4>Read the verdict</h4><p>Every credit attributed with evidence,
      the Razorpay slice reconciled to the paise, a fee-GST schedule, and an exception queue with next actions.</p></div>
  </div>

  <h2 class="section-h">Who it's for</h2>
  <p class="section-s">One tool, three jobs.</p>
  <div class="who">
    <div class="wc"><div class="k">Merchants</div><p>Stop eyeballing the statement every Monday. Know in seconds
      what settled, what's missing, and what that random NEFT actually was.</p></div>
    <div class="wc"><div class="k">Accountants &amp; CAs</div><p>A paise-exact reconciliation schedule and a fee-GST
      input-credit working paper, exportable, with an evidence trail behind every figure.</p></div>
    <div class="wc"><div class="k">Developers</div><p>A deterministic engine with a CLI and a local REST API.
      POST three files, get <span style="font-family:var(--mono)">report.json</span>. Open source, no black box.</p></div>
  </div>

  <h2 class="section-h">Questions worth asking</h2>
  <div class="faq">
    <details><summary>Why abstain instead of giving me a best guess?</summary>
      <p>Because a wrong “this is Razorpay's” is more expensive than a blank. It silently corrupts your books and
      your GST filing, and someone has to find and unwind it weeks later. An honest “needs review” costs a
      two-minute look now. We only auto-attribute where the expected cost of being wrong is below the cost of a
      review — everything else is surfaced, not guessed.</p></details>
    <details><summary>How is this different from Razorpay's own reconciliation?</summary>
      <p>A gateway reconciles its own settlements against its own records. untangle works on <i>your</i> bank
      account, where Razorpay is only one of several credit sources, and its job is attribution across all of
      them plus calibrated abstention — not matching within one rail.</p></details>
    <details><summary>Do you store my bank statement?</summary>
      <p>No. Files are reconciled and discarded — no database, no <b>persistent</b> storage, no analytics on your
      financials, no signup. (A request writes its uploads to a private temporary file only for the duration of
      the run, then deletes it.) It's open source, so you can read the exact code that touches your file, or run
      it on your own machine where nothing leaves it at all.</p></details>
    <details><summary>Is the precision claim real or marketing?</summary>
      <p>It's measured on a sealed, generator-blind benchmark and reported with its scope. The engine never
      imports the data generator or reads ground truth. On your own unlabelled upload we don't claim a precision
      number we can't measure — we show attributed-vs-abstained counts and a real coverage curve instead.</p></details>
    <details><summary>Why not PDF statements?</summary>
      <p>PDF parsing gets money wrong silently, and we'd rather refuse than guess a decimal place. Every bank's
      netbanking exports CSV — use that. XLSX support is coming.</p></details>
  </div>

  <div class="privacy"><h3>untangle never stores your data.</h3>
    <p>Files are processed and discarded when the result expires — no database, no persistent storage, no analytics on
    your financials, no signup. It's open source: verify the code that handles your file, or run it on your own machine.</p></div>

  <div class="finalcta">
    <h2>See it refuse to guess.</h2>
    <p>Run the full pipeline on a realistic sample statement — attribution, abstention, reconciliation and fee-GST — in one click.</p>
    <div class="ctarow" style="justify-content:center">
      <a class="cta primary" href="/try-sample">Try the sample →</a>
      <a class="cta ghost" href="/app">Reconcile my own files</a>
    </div>
  </div>
</div>""" + _FOOT


def upload_page() -> str:
    return _HEAD.format(title="untangle — reconcile your statement") + """
<div class="wrap" style="padding-top:48px">
  <p class="eyebrow">Reconcile</p>
  <h1 style="font-size:34px">Drop your three files.</h1>
  <p class="sub" style="margin-bottom:8px">CSV bank statement, Razorpay settlement report, and your order list.
  Processed in memory — nothing is saved.</p>

  <form action="/reconcile" method="post" enctype="multipart/form-data" id="f" class="up">
    <div class="drops">
      <label class="drop req">
        <span class="num">1</span>
        <h4>Bank statement</h4><p class="hint">CSV from your netbanking</p>
        <div class="cols">value_date · narration · credit · debit</div>
        <input type="file" name="bank" accept=".csv,text/csv" required>
        <span class="pick">Choose file</span><span class="droptip">or drop it here</span>
        <span class="status"></span>
      </label>
      <label class="drop req">
        <span class="num">2</span>
        <h4>Razorpay settlement report</h4><p class="hint">Dashboard → Settlements → Reports</p>
        <div class="cols">entity_id · type · amount · fee · tax · settlement_utr</div>
        <input type="file" name="recon" accept=".json,application/json" required>
        <span class="pick">Choose file</span><span class="droptip">or drop it here</span>
        <span class="status"></span>
      </label>
      <label class="drop req">
        <span class="num">3</span>
        <h4>Order ledger</h4><p class="hint">Your orders export (CSV)</p>
        <div class="cols">order_id · amount_paise · status</div>
        <input type="file" name="ledger" accept=".csv,text/csv" required>
        <span class="pick">Choose file</span><span class="droptip">or drop it here</span>
        <span class="status"></span>
      </label>
    </div>

    <div class="note"><b>PDF statements: not yet.</b> PDF parsing gets money wrong silently, and we'd rather refuse
    than guess. Every bank's netbanking exports CSV — use that. (XLSX support is coming.) Max 15 MB per file.</div>

    <div class="submit">
      <button class="cta primary" type="submit">Reconcile →</button>
      <a class="cta ghost" href="/try-sample">Or try with sample data</a>
    </div>
  </form>

  <div class="privacy" style="margin-top:34px"><h3>Why it's safe to upload here.</h3>
    <p>Your files never touch a database or persistent disk — they're read into memory, reconciled, and discarded.
    No account, no tracking. Don't take our word for it: it's open source, so read the code, or clone and run it on
    localhost where nothing leaves your machine at all.</p></div>

  <h2 class="section-h" style="margin-top:56px;font-size:22px">On the roadmap — and honestly not yet</h2>
  <div class="roadmap">
    <div class="rc"><div class="t">Connect your Razorpay account<span class="soon">soon</span></div>
      Pull the settlement report directly with an API key — file upload today, because we won't hold your keys until
      key-handling is production-hardened.</div>
    <div class="rc"><div class="t">Bank feeds via Account Aggregator<span class="soon">soon</span></div>
      Regulated territory (FIU licensing) — real, not faked. Upload your statement for now.</div>
  </div>
</div>
<script>
(function(){
  function update(inp){
    var d=inp.closest('.drop'), s=d.querySelector('.status');
    if(inp.files&&inp.files[0]){
      d.classList.add('ok');
      var kb=Math.max(1,Math.round(inp.files[0].size/1024));
      s.textContent='✓ '+inp.files[0].name+' · '+kb+' KB';
    }else{ d.classList.remove('ok'); s.textContent=''; }
  }
  document.querySelectorAll('.drop').forEach(function(d){
    var inp=d.querySelector('input[type=file]');
    inp.addEventListener('change',function(){update(inp);});
    ['dragenter','dragover'].forEach(function(e){
      d.addEventListener(e,function(ev){ev.preventDefault();ev.stopPropagation();d.classList.add('drag');});
    });
    ['dragleave','dragend'].forEach(function(e){
      d.addEventListener(e,function(ev){ev.preventDefault();ev.stopPropagation();d.classList.remove('drag');});
    });
    d.addEventListener('drop',function(ev){
      ev.preventDefault();ev.stopPropagation();d.classList.remove('drag');
      if(ev.dataTransfer&&ev.dataTransfer.files&&ev.dataTransfer.files.length){
        inp.files=ev.dataTransfer.files; update(inp);
      }
    });
  });
})();
</script>""" + _FOOT


_VERIFY_CSS = """<style>
.vmono{font-family:var(--mono)}
.vlede{font-size:16px;color:var(--ts);max-width:66ch;margin:18px 0 24px;line-height:1.6}
.vlede b{color:var(--tp)}
#certin{width:100%;min-height:170px;padding:14px 16px;border:1px solid var(--border);border-radius:12px;
  background:var(--surface);color:var(--tp);font-family:var(--mono);font-size:12.5px;line-height:1.5;resize:vertical;outline:none}
#certin:focus{border-color:var(--acc)}
.vrow{display:flex;gap:12px;align-items:center;margin-top:14px;flex-wrap:wrap}
.vres{margin-top:24px;border:1px solid var(--border);border-radius:14px;background:var(--surface);padding:24px 26px;display:none}
.vverdict{display:flex;align-items:center;gap:12px;font-family:var(--disp);font-weight:480;font-size:24px;letter-spacing:-.01em}
.vcheck{width:32px;height:32px;border-radius:50%;display:grid;place-items:center;color:#fff;flex-shrink:0;font-size:16px}
.vkv{margin-top:18px;display:grid;grid-template-columns:auto 1fr;gap:10px 20px;font-size:13.5px}
.vkv .k{color:var(--ts)}.vkv .v{word-break:break-all}.vkv .v.vmono{font-size:12px}
.vpill{display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:500;padding:3px 11px;border-radius:999px}
.vpill.ok{background:rgba(27,122,77,.12);color:var(--ok)}
.vpill.bad{background:rgba(178,59,59,.12);color:#b23b3b}
.vpill.na{background:var(--sunken);color:var(--tt)}
.vnote{margin-top:16px;font-size:12px;color:var(--tt);line-height:1.55}
</style>"""


def verify_page() -> str:
    return _HEAD.format(title="untangle — verify a close certificate") + _VERIFY_CSS + """
<div class="wrap" style="padding-top:48px;max-width:820px">
  <p class="eyebrow">Independent verification</p>
  <h1 style="font-size:38px">Verify a close certificate.</h1>
  <p class="vlede">Paste an untangle close-certificate (the JSON from <span class="vmono">Download close certificate</span>,
  or <a href="/api/certificate/sample">the sample</a>). This page re-derives its <b>SHA-256 content hash</b> and,
  when the certificate is signed, checks the <b>ECDSA (P-256) signature against untangle's pinned issuer
  key</b> (not a key inside the certificate) — a tampered field breaks the hash; a certificate signed with
  any other key fails. Attach the run's report to also re-run every proof-packet check; each accepted
  verdict rests on a report-backed tie you can re-derive from the source records.</p>

  <textarea id="certin" placeholder='Paste the certificate JSON here, e.g. {"certificate":{...},"content_sha256":"...","signature":"..."}'></textarea>
  <div class="vrow">
    <button class="cta primary" onclick="doVerify()">Verify certificate</button>
    <button class="cta ghost" onclick="loadSample()">Load the sample certificate</button>
  </div>
  <div class="vres" id="vres"></div>
  <p class="vnote">An unsigned certificate's matching hash is recomputable by anyone and is not authenticity.
  Signed results use this deployment's pinned issuer key. Packet checks apply to the attached bound report;
  they do not re-audit the original bank, settlement, or ledger files. Nothing you paste here is stored.</p>
</div>
<script>
function vpill(v){ if(v===true) return '<span class="vpill ok">\\u2713 valid</span>';
  if(v===false) return '<span class="vpill bad">\\u2717 invalid</span>';
  return '<span class="vpill na">not applicable</span>'; }
function esc(s){ var d=document.createElement('span'); d.textContent=(s==null?'':String(s)); return d.innerHTML; }
function show(d){
  var box=document.getElementById('vres'); box.style.display='block';
  if(d && d.error){ box.innerHTML='<div class="vverdict"><span class="vcheck" style="background:#b23b3b">\\u2717</span>'+esc(d.error)+'</div>'; return; }
  var authentic = (d.authenticated===true) && (d.hash_matches===true) &&
                  (d.report_binding_valid!==false) &&
                  (d.packets_passed==null || d.packets_passed===d.packets_verified);
  var col = authentic ? 'var(--ok)' : '#b23b3b';
  var pk = d.packets_verified!=null ? ('<div class="k">Proof packets re-verified</div><div class="v">'+d.packets_passed+' / '+d.packets_verified+' pass</div>') : '';
  box.innerHTML =
    '<div class="vverdict"><span class="vcheck" style="background:'+col+'">'+(authentic?'\\u2713':'\\u2717')+'</span>'+
      (authentic?'Authentic &amp; untampered':(d.signed===false && d.hash_matches===true ? 'Hash consistent (unsigned)' : 'Verification failed'))+'</div>'+\
    '<div class="vkv">'+
      '<div class="k">Content hash re-derived</div><div class="v vmono">'+esc(d.content_hash||'')+'</div>'+
      '<div class="k">Hash matches the certificate</div><div class="v">'+vpill(d.hash_matches)+'</div>'+
      (d.report_binding_valid!==null && d.report_binding_valid!==undefined ? '<div class="k">Attached report matches issuer binding</div><div class="v">'+vpill(d.report_binding_valid)+'</div>' : '')+
      '<div class="k">ECDSA signature</div><div class="v">'+(d.signed?vpill(d.signature_valid):'<span class="vpill na">unsigned (hash-only)</span>')+'</div>'+
      pk +
      (d.audit_root?'<div class="k">Report audit root</div><div class="v vmono">'+esc(d.audit_root)+'</div>':'')+
      (d.summary?'<div class="k">Summary</div><div class="v">'+esc(d.summary)+'</div>':'')+
    '</div>';
}
async function doVerify(){
  var el=document.getElementById('certin'); var payload;
  try{ payload=JSON.parse(el.value); }catch(e){ return show({error:'That is not valid JSON. Paste the whole certificate object.'}); }
  try{ var r=await fetch('/api/verify',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}); show(await r.json()); }
  catch(e){ show({error:'Could not reach the verifier.'}); }
}
async function loadSample(){
  try{ var r=await fetch('/api/certificate/sample'); var cert=await r.json();
    document.getElementById('certin').value=JSON.stringify(cert,null,2); doVerify(); }
  catch(e){ show({error:'Could not load the sample certificate.'}); }
}
</script>""" + _FOOT
