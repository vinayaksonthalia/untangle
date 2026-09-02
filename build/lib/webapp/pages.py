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
    return (
        _HEAD.format(title="untangle — verify a close certificate")
        + _VERIFY_CSS
        + """
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
</script>"""
        + _FOOT
    )
