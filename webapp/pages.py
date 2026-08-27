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
.drops{{display:grid;grid-template-columns:repeat(3,1fr);gap:18px;margin:28px 0}}
.drop{{background:var(--surface);border:1.5px dashed var(--border2);border-radius:12px;padding:22px;text-align:center;position:relative;transition:border-color .15s,background .15s}}
.drop.req.ok{{border-style:solid;border-color:var(--ok);background:#f4faf6}}
.drop h4{{font-size:14px;margin:0 0 4px}}.drop .hint{{color:var(--tt);font-size:12px;margin:0 0 12px}}
.drop .cols{{font-family:var(--mono);font-size:10.5px;color:var(--ts);background:var(--sunken);border:1px solid var(--border);border-radius:6px;padding:5px 8px;display:inline-block;margin-bottom:12px}}
.drop input[type=file]{{font-size:12px;width:100%}}
.drop .status{{font-size:12px;color:var(--ok);margin-top:8px;min-height:16px}}
.note{{background:var(--sunken);border:1px solid var(--border);border-radius:10px;padding:16px 18px;color:var(--ts);font-size:13px;margin:20px 0}}
.note b{{color:var(--tp)}}
.submit{{display:flex;gap:14px;align-items:center;flex-wrap:wrap;margin-top:8px}}
.roadmap{{display:grid;grid-template-columns:repeat(2,1fr);gap:16px;margin-top:20px}}
.rc{{border:1px dashed var(--border2);border-radius:10px;padding:16px;color:var(--ts);font-size:13px;background:var(--sunken);opacity:.9}}
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
/* final cta */
.finalcta{margin-top:96px;text-align:center;background:var(--surface);border:1px solid var(--border);border-radius:16px;padding:52px 30px}
.finalcta h2{font-family:var(--disp);font-weight:480;font-size:32px;letter-spacing:-.01em;margin:0 0 10px}
.finalcta p{color:var(--ts);margin:0 auto 26px;max-width:52ch}
@media(max-width:840px){.hero{grid-template-columns:1fr;gap:34px}.trap{grid-template-columns:1fr;gap:26px}
.stats{grid-template-columns:repeat(2,1fr)}.hero-copy h1{max-width:none}}
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
    <rect x="12" y="34" width="118" height="30" rx="7" fill="#fff" stroke="#e6e4df"/><text x="24" y="53">₹2,14,320</text>
    <rect x="12" y="78" width="118" height="30" rx="7" fill="#fff" stroke="#e6e4df"/><text x="24" y="97">₹  88,400</text>
    <rect x="12" y="122" width="118" height="30" rx="7" fill="#fff" stroke="#e6e4df"/><text x="24" y="141">₹  12,500</text>
    <rect x="12" y="166" width="118" height="30" rx="7" fill="#fff" stroke="#e6e4df"/><text x="24" y="185">₹  49,999</text>
    <rect x="12" y="210" width="118" height="30" rx="7" fill="#fff" stroke="#e6e4df"/><text x="24" y="229">₹  31,050</text>
  </g>
  <!-- connectors -->
  <g fill="none" stroke="#c9c7c0" stroke-width="1.4" marker-end="url(#ah)">
    <path d="M132,49 C210,49 214,52 296,52"/>
    <path d="M132,93 C210,93 214,52 296,56" opacity=".85"/>
    <path d="M132,137 C210,137 214,100 296,100"/>
    <path d="M132,180 C210,180 214,148 296,148"/>
    <path d="M132,224 C214,224 220,210 296,210" stroke="#e0b877" stroke-dasharray="4 3"/>
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
    return _HEAD.format(title="untangle — which of these credits is even Razorpay's?") + _LANDING_CSS + """
<div class="wrap">
  <div class="hero">
    <div class="hero-copy">
      <span class="badge"><span class="dot"></span>Precision-first · abstains rather than mislabel</span>
      <h1>Which of these credits is even Razorpay's?</h1>
      <p class="sub">Settlements, a second gateway, direct UPI, COD remittances, the odd personal transfer — all
      landing in one current account. untangle attributes every bank credit to its rail <b>with evidence</b>,
      reconciles the Razorpay slice to the paise, and recovers the GST on gateway fees. When the evidence is
      weak, it says so — it never force-books a guess.</p>
      <div class="ctarow">
        <a class="cta primary" href="/try-sample">See it on sample data →</a>
        <a class="cta ghost" href="/app">Reconcile my statement</a>
        <span class="free">free · no signup · nothing stored</span>
      </div>
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

  <!-- PROOF -->
  <div class="proof">
    <p class="lab">Measured on the sealed, generator-blind benchmark</p>
    <h2>The number that matters isn't how much it matches. It's how rarely it's wrong.</h2>
    <div class="stats">
      <div class="stat"><div class="v ok">1.000</div><div class="k">Razorpay attribution precision — zero false “this is Razorpay's”</div></div>
      <div class="stat"><div class="v ok">0</div><div class="k">Decoy false-positives, across 173 look-alike non-Razorpay credits</div></div>
      <div class="stat"><div class="v">0.95</div><div class="k">Recall on true Razorpay credits — including split legs recovered by provable set-sum; the rest abstain, never guessed</div></div>
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

  <form action="/reconcile" method="post" enctype="multipart/form-data" id="f">
    <div class="drops">
      <div class="drop req" data-req>
        <h4>Bank statement</h4><p class="hint">CSV from your netbanking</p>
        <div class="cols">value_date · narration · credit · debit</div>
        <input type="file" name="bank" accept=".csv,text/csv" required onchange="mark(this)">
        <div class="status"></div>
      </div>
      <div class="drop req" data-req>
        <h4>Razorpay settlement report</h4><p class="hint">Dashboard → Settlements → Reports</p>
        <div class="cols">entity_id · amount · fee · tax · settlement_utr</div>
        <input type="file" name="recon" accept=".json,application/json" required onchange="mark(this)">
        <div class="status"></div>
      </div>
      <div class="drop req" data-req>
        <h4>Order ledger</h4><p class="hint">Your orders export (CSV)</p>
        <div class="cols">order_id · amount · status</div>
        <input type="file" name="ledger" accept=".csv,text/csv" required onchange="mark(this)">
        <div class="status"></div>
      </div>
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
function mark(inp){var d=inp.closest('.drop');var s=d.querySelector('.status');
if(inp.files&&inp.files[0]){d.classList.add('ok');var kb=Math.max(1,Math.round(inp.files[0].size/1024));
s.textContent='✓ '+inp.files[0].name+' ('+kb+' KB)';}else{d.classList.remove('ok');s.textContent='';}}
</script>""" + _FOOT
