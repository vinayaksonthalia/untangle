"""Server-rendered landing + upload pages, in the dashboard's design system."""

from __future__ import annotations

import pathlib
from functools import cache

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


_TEMPLATE_DIR = pathlib.Path(__file__).resolve().parent / "templates"


@cache
def _load_template(name: str) -> str:
    """Load a committed HTML template from webapp/templates, failing loudly.

    The landing page is a static, pre-built artifact (see tools/tailwind/build.sh):
    a missing or empty file is a build/packaging error, never a blank page served
    to a user, so raise rather than degrade silently.
    """
    path = _TEMPLATE_DIR / name
    if not path.is_file():
        raise FileNotFoundError(f"landing template not found: {path}")
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError(f"landing template is empty: {path}")
    return text


def landing_page() -> str:
    """Return the pre-built landing page (self-hosted fonts + compiled CSS)."""
    return _load_template("landing.html")


def upload_page() -> str:
    return (
        _HEAD.format(title="untangle — reconcile your statement")
        + """
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
</script>"""
        + _FOOT
    )


def verify_page() -> str:
    """Return the pre-built verify page (self-hosted fonts + compiled CSS)."""
    return _load_template("verify.html")


def dashboard_page() -> str:
    """Return the pre-built dashboard (its JS fetches live figures from /api/presentation)."""
    return _load_template("dashboard.html")
