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


def landing_page() -> str:
    return _HEAD.format(title="untangle — which of these credits is even Razorpay's?") + """
<div class="wrap">
  <p class="eyebrow">Multi-rail settlement reconciliation</p>
  <h1>Your bank account is a pile of credits. Which ones are even Razorpay's?</h1>
  <p class="sub">Settlements, a second gateway, direct UPI, COD remittances, the odd personal transfer —
  all landing in one current account. untangle reads your bank statement, attributes every credit to its
  rail with evidence, reconciles the Razorpay slice to the paise, and shows the GST on gateway fees
  you're entitled to claim back.</p>
  <div class="ctarow">
    <a class="cta primary" href="/app">Reconcile my statement</a>
    <a class="cta ghost" href="/try-sample">See it on sample data →</a>
    <span class="free">free · no signup · nothing stored</span>
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

  <h2 class="section-h">How it works</h2>
  <p class="section-s">Three files in, a paise-exact verdict out. No account, no storage.</p>
  <div class="steps">
    <div class="step"><div class="n">01</div><h4>Export three files</h4><p>Your bank statement (CSV from netbanking),
      your Razorpay settlement report (Dashboard → Settlements → Reports), your order list.</p></div>
    <div class="step"><div class="n">02</div><h4>Drop them here</h4><p>Processed in memory and discarded after.
      No account, no database, nothing saved to disk.</p></div>
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
      POST three files, get <span style="font-family:var(--mono)">report.json</span>. Open source, 37 tests, no black box.</p></div>
  </div>

  <div class="privacy"><h3>untangle never stores your data.</h3>
    <p>Files are processed in memory and discarded when the result expires — no database, no disk, no analytics on
    your financials, no signup. It's open source: verify the code that handles your file, or run it on your own machine.</p></div>
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
