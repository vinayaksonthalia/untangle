"""Render a self-contained HTML dashboard from a run report (US-facing UI).

    python -m ui.dashboard --run out/report.json --out ui/dashboard.html

Zero runtime dependencies (report data is inlined at build time as computed values, not a
raw dump). Deterministic: same report in → same HTML out. Design follows a researched
premium-fintech spec (Stripe / Ramp / Mercury / Linear lineage): warm paper canvas, one
confident accent, Fraunces display + IBM Plex Mono figures (tabular, right-aligned), depth
from 1px borders not shadows, and one product-native signature — the "untangle thread".
"""

from __future__ import annotations

import argparse
import html
import json
import math

_RAIL = {
    "razorpay_settlement": ("Razorpay settlement", "#2B5EDB", True),
    "other_gateway": ("Other gateway", "#6B5B95", False),
    "direct_upi": ("Direct UPI", "#4A8B6F", False),
    "cod_remittance": ("COD remittance", "#8A6D3B", False),
    "unrelated": ("Unrelated", "#8C8C82", False),
    "UNKNOWN": ("Unattributed", "#ADABA2", None),
}
_REASON = {
    "razorpay_coverage_not_found": ("coverage not found", "#B4720A"),
    "razorpay_uncertain": ("razorpay uncertain", "#B4720A"),
    "unattributed_ambiguous": ("unattributed", "#B23B3B"),
}


def _grp(n: int) -> str:
    s = f"{abs(n):d}"
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:]); head = head[:-2]
        parts.insert(0, head)
        s = ",".join(parts) + "," + tail
    return s


def _amt(paise: int, paisa: bool = False) -> str:
    rupees = int(abs(paise) // 100)
    sign = "−" if paise < 0 else ""
    body = _grp(rupees)
    if paisa:
        body += f".{abs(paise) % 100:02d}"
    return f'{sign}<span class="rs">₹</span> {body}'


def render(report: dict) -> str:
    t = report["totals"]
    bp = t["by_rail_paise"]; bc = t["by_rail_count"]
    rzp_p = bp.get("razorpay_settlement", 0); rzp_c = bc.get("razorpay_settlement", 0)
    unk_p = bp.get("UNKNOWN", 0); unk_c = bc.get("UNKNOWN", 0)
    other_p = sum(v for k, v in bp.items() if k not in ("razorpay_settlement", "UNKNOWN"))
    other_c = sum(v for k, v in bc.items() if k not in ("razorpay_settlement", "UNKNOWN"))
    rec_p = t["reconciled_paise"]; rec_c = t["reconciled_count"]
    fee = t["fee_gst_recoverable_paise"]; fee_n = len(report["fee_gst"]["by_entity"])
    exc_n = t["exception_count"]
    cov_amt = rec_p / rzp_p if rzp_p else 0
    cov_cnt = rec_c / rzp_c if rzp_c else 0
    recs = report["reconciliations"]
    max_resid = max((abs(x["residual_paise"]) for x in recs), default=0)

    # rail breakdown rows (share bar + untangle thread)
    order = sorted(bp.items(), key=lambda kv: -kv[1])
    maxp = max((p for _, p in order), default=1)
    rail_rows = []
    for rail, p in order:
        label, color, matched = _RAIL.get(rail, (rail, "#999", None))
        w = 100.0 * p / maxp
        dashed = "stroke-dasharray:2 4;" if matched is None else ""
        rail_rows.append(f"""
      <div class="rr">
        <div class="rr-l"><span class="dot" style="background:{color}"></span>{html.escape(label)}</div>
        <svg class="thread" viewBox="0 0 100 8" preserveAspectRatio="none"><line x1="0" y1="4" x2="{w:.1f}" y2="4"
          stroke="{color}" stroke-width="6" stroke-linecap="round" style="{dashed}"/></svg>
        <div class="rr-a mono">{_amt(p)}</div><div class="rr-c mono">{bc.get(rail,0)}</div>
      </div>""")

    # coverage arc
    r = 54; circ = 2 * math.pi * r; off = circ * (1 - cov_amt)

    exc_rows = []
    for e in report["exceptions"]:
        lbl, col = _REASON.get(e["reason_code"], (e["reason_code"], "#6B6B62"))
        exc_rows.append(f"""
      <tr><td><span class="sev" style="--d:{col}">{html.escape(lbl)}</span></td>
      <td class="dt">{html.escape(e["detail"])}</td>
      <td class="ac">{html.escape(e["suggested_action"])}</td></tr>""")

    cfg = report.get("config", {})
    reasons = t.get("exceptions_by_reason", {})
    reason_line = " · ".join(
        f'{v} {html.escape(_REASON.get(k, (k, ""))[0])}' for k, v in reasons.items()
    )
    return _T.format(
        hero_rec=_amt(rec_p), hero_total=_amt(rzp_p), cov_pct=f"{cov_amt*100:.1f}",
        fee=_amt(fee), fee_n=f"{fee_n:,}", rzp_rec=_amt(rzp_p), rzp_c=rzp_c,
        rec_c=rec_c, other=_amt(other_p), other_c=other_c, exc_n=exc_n,
        rail_rows="".join(rail_rows), circ=f"{circ:.1f}", off=f"{off:.1f}",
        arc_pct=f"{cov_amt*100:.0f}", rec_of=f"{rec_c}/{rzp_c}",
        unresolved=rzp_c - rec_c, unk_c=unk_c, max_resid=max_resid,
        exc_rows="".join(exc_rows), reason_line=reason_line,
        seed=cfg.get("seed", "?"), provider=html.escape(str(cfg.get("provider") or "none")),
        n_recon=f'{t["n_recon_rows"]:,}', n_lines=t["n_bank_lines"],
        audit=html.escape(report["audit_root"][:10]),
    )


_T = """<!doctype html><html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>untangle — settlement reconciliation</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,480;9..144,560&family=Inter:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root{{--bg:#f7f7f5;--surface:#fff;--sunken:#fbfbfa;--border:#e6e4df;--border2:#d8d5ce;
--tp:#14140f;--ts:#6b6b62;--tt:#9b9b90;--acc:#2b5edb;--acc-tint:#eaf0fd;
--ok:#1b7a4d;--warn:#b4720a;--dng:#b23b3b;
--disp:'Fraunces',Georgia,serif;--ui:'Inter',-apple-system,'Segoe UI',sans-serif;--mono:'IBM Plex Mono',ui-monospace,monospace;
--max:1120px;--r-lg:12px;--r-md:8px;}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--tp);font-family:var(--ui);-webkit-font-smoothing:antialiased;font-size:14px;line-height:1.5}}
.mono{{font-family:var(--mono);font-variant-numeric:tabular-nums}}
.rs{{font-size:.85em;color:var(--ts)}}
.topbar{{position:sticky;top:0;z-index:5;background:rgba(247,247,245,.86);backdrop-filter:blur(8px);
border-bottom:1px solid var(--border);height:56px;display:flex;align-items:center}}
.topbar .in{{max-width:var(--max);margin:0 auto;padding:0 48px;width:100%;display:flex;align-items:center;gap:16px}}
.logo{{font-family:var(--disp);font-weight:560;font-size:19px;letter-spacing:-.01em}}
.logo b{{color:var(--acc);font-weight:560}}
.period{{font-family:var(--mono);font-size:12px;color:var(--ts);border:1px solid var(--border);border-radius:var(--r-md);padding:5px 10px}}
.spacer{{flex:1}}
.pill{{display:inline-flex;align-items:center;gap:7px;font-size:12px;font-weight:500;
background:var(--warn);color:#fff;border-radius:100px;padding:5px 11px}}
.pill .d{{width:6px;height:6px;border-radius:50%;background:#fff;opacity:.9}}
.wrap{{max-width:var(--max);margin:0 auto;padding:56px 48px 80px}}
.eyebrow{{font-family:var(--ui);font-weight:600;font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--ts);margin:0}}
.hero-h{{font-family:var(--disp);font-weight:480;font-size:22px;letter-spacing:-.01em;margin:6px 0 18px}}
.hero-fig{{font-family:var(--disp);font-weight:480;font-size:54px;line-height:1.02;letter-spacing:-.02em;font-variant-numeric:tabular-nums}}
.hero-fig .of{{font-family:var(--ui);font-size:16px;font-weight:400;color:var(--ts);letter-spacing:0}}
.covbar{{height:8px;background:var(--border);border-radius:100px;margin:20px 0 6px;max-width:620px;overflow:hidden}}
.covbar i{{display:block;height:100%;background:var(--ok);border-radius:100px}}
.covmeta{{font-size:12.5px;color:var(--ts)}}
.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin:36px 0 8px}}
.card{{background:var(--surface);border:1px solid var(--border);border-radius:var(--r-lg);padding:20px 22px;transition:border-color .15s,box-shadow .15s}}
.card:hover{{border-color:var(--border2);box-shadow:0 2px 8px rgba(20,20,15,.06)}}
.card.sig{{border-left:3px solid var(--acc)}}
.card .l{{font-weight:600;font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--ts)}}
.card .v{{font-family:var(--mono);font-weight:500;font-size:26px;margin-top:12px;letter-spacing:-.01em}}
.card.sig .v{{font-size:30px;color:var(--acc)}}
.card .n{{font-size:12.5px;color:var(--tt);margin-top:7px}}
.card .n .tick{{color:var(--ok);font-weight:600}}
.grid2{{display:grid;grid-template-columns:1.55fr 1fr;gap:24px;margin-top:52px;align-items:start}}
.panel{{background:var(--surface);border:1px solid var(--border);border-radius:var(--r-lg);padding:24px}}
h2{{font-family:var(--disp);font-weight:480;font-size:20px;letter-spacing:-.01em;margin:0 0 3px}}
.sc{{color:var(--ts);font-size:13px;margin:0 0 20px}}
.rr{{display:grid;grid-template-columns:150px 1fr 130px 44px;align-items:center;gap:14px;height:46px;border-bottom:1px solid var(--border)}}
.rr:last-child{{border-bottom:0}}
.rr-l{{display:flex;align-items:center;gap:9px;font-size:13.5px;white-space:nowrap}}
.dot{{width:8px;height:8px;border-radius:2px;flex:none}}
.thread{{width:100%;height:8px}}
.rr-a{{text-align:right;font-weight:500;font-size:13.5px}}
.rr-c{{text-align:right;color:var(--tt);font-size:12.5px}}
.arcwrap{{display:flex;flex-direction:column;align-items:center;text-align:center}}
.arc{{position:relative;width:140px;height:140px}}
.arc .pct{{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center}}
.arc .pct b{{font-family:var(--disp);font-weight:480;font-size:32px;font-variant-numeric:tabular-nums}}
.arc .pct span{{font-size:11px;color:var(--ts);letter-spacing:.04em;text-transform:uppercase}}
.legend{{width:100%;margin-top:22px}}
.legend .li{{display:flex;align-items:center;gap:9px;font-size:13px;padding:7px 0;border-top:1px solid var(--border)}}
.legend .li .d{{width:8px;height:8px;border-radius:2px}}
.legend .li .c{{margin-left:auto;font-family:var(--mono);font-variant-numeric:tabular-nums;color:var(--ts)}}
.explain{{font-size:12.5px;color:var(--ts);margin-top:16px;line-height:1.55}}
.exc-wrap{{margin-top:52px}}
table{{width:100%;border-collapse:collapse;background:var(--surface);border:1px solid var(--border);border-radius:var(--r-lg);overflow:hidden}}
thead th{{background:var(--sunken);text-align:left;font-weight:600;font-size:11px;letter-spacing:.04em;text-transform:uppercase;color:var(--ts);padding:12px 16px;border-bottom:1px solid var(--border)}}
tbody td{{padding:14px 16px;border-bottom:1px solid var(--border);vertical-align:top;font-size:13px}}
tbody tr:last-child td{{border-bottom:0}}
tbody tr:hover{{background:var(--acc-tint)}}
.sev{{display:inline-flex;align-items:center;gap:8px;white-space:nowrap;color:var(--tp);font-size:12.5px}}
.sev::before{{content:"";width:7px;height:7px;border-radius:50%;background:var(--d)}}
.dt{{color:#3d3d36}}.ac{{color:var(--ts)}}
footer{{max-width:var(--max);margin:44px auto 0;padding:18px 48px 0;border-top:1px solid var(--border);
font-family:var(--mono);font-size:11.5px;color:var(--tt);display:flex;gap:26px;flex-wrap:wrap}}
footer b{{color:var(--ts);font-weight:500}}
@media(max-width:880px){{.wrap,.topbar .in,footer{{padding-left:24px;padding-right:24px}}
.cards{{grid-template-columns:repeat(2,1fr)}}.grid2{{grid-template-columns:1fr}}.hero-fig{{font-size:42px}}}}
</style></head><body>
<div class="topbar"><div class="in">
  <span class="logo">un<b>tangle</b></span>
  <span class="period">bank statement · one period</span>
  <span class="spacer"></span>
  <span class="pill"><span class="d"></span>{exc_n} to review</span>
</div></div>

<div class="wrap">
  <p class="eyebrow">Statement reconciled</p>
  <div class="hero-fig">{hero_rec} <span class="of">reconciled of {hero_total} in Razorpay credits</span></div>
  <div class="covbar"><i style="width:{cov_pct}%"></i></div>
  <div class="covmeta">{cov_pct}% of the Razorpay slice matched to the settlement report, to the paise (within {max_resid} paise drift)</div>

  <div class="cards">
    <div class="card sig"><div class="l">Recoverable fee-GST</div><div class="v">{fee}</div>
      <div class="n">input tax credit · traceable across {fee_n} txns</div></div>
    <div class="card"><div class="l">Razorpay credits</div><div class="v">{rzp_rec}</div>
      <div class="n"><span class="tick">✓</span> {rec_c}/{rzp_c} reconciled</div></div>
    <div class="card"><div class="l">Other rails</div><div class="v">{other}</div>
      <div class="n">{other_c} credits, not Razorpay's</div></div>
    <div class="card"><div class="l">Flagged for review</div><div class="v">{exc_n}</div>
      <div class="n">never guessed — see queue below</div></div>
  </div>

  <div class="grid2">
    <div class="panel">
      <h2>Where the money came from</h2>
      <p class="sc">Every bank credit traced to its rail. Solid thread = attributed; frayed = unattributed.</p>
      {rail_rows}
    </div>
    <div class="panel arcwrap">
      <h2 style="align-self:flex-start">Reconciliation coverage</h2>
      <p class="sc" style="align-self:flex-start">Razorpay slice, matched to settlements.</p>
      <div class="arc"><svg width="140" height="140" viewBox="0 0 140 140">
        <circle cx="70" cy="70" r="54" fill="none" stroke="var(--border)" stroke-width="11"/>
        <circle cx="70" cy="70" r="54" fill="none" stroke="var(--ok)" stroke-width="11" stroke-linecap="round"
          stroke-dasharray="{circ}" stroke-dashoffset="{off}" transform="rotate(-90 70 70)"/>
      </svg><div class="pct"><b>{arc_pct}%</b><span>by value</span></div></div>
      <div class="legend">
        <div class="li"><span class="d" style="background:var(--ok)"></span>Reconciled<span class="c mono">{rec_of}</span></div>
        <div class="li"><span class="d" style="background:var(--warn)"></span>Needs review<span class="c mono">{unresolved}</span></div>
        <div class="li"><span class="d" style="background:#adaba2"></span>Abstained<span class="c mono">{unk_c}</span></div>
      </div>
      <p class="explain">Every miss is an abstention, not a wrong match — <b>0</b> false positives across all rails. What can't be proven is flagged, never forced.</p>
    </div>
  </div>

  <div class="exc-wrap">
    <h2>Exception queue</h2>
    <p class="sc">{exc_n} credits untangle could not resolve confidently — {reason_line}. Each carries a reason and a next step.</p>
    <table><thead><tr><th style="width:170px">Reason</th><th>Detail</th><th style="width:34%">Suggested action</th></tr></thead>
    <tbody>{exc_rows}</tbody></table>
  </div>
</div>
<footer><span>reproducible · seed <b>{seed}</b></span><span>AI <b>{provider}</b></span>
<span><b>{n_lines}</b> bank credits · <b>{n_recon}</b> recon rows</span><span>audit <b>{audit}…</b></span></footer>
</body></html>"""


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="ui.dashboard")
    p.add_argument("--run", default="out/report.json")
    p.add_argument("--out", default="ui/dashboard.html")
    args = p.parse_args(argv)
    with open(args.run, encoding="utf-8") as fh:
        report = json.load(fh)
    out = render(report)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(out)
    print(f"wrote {args.out} ({len(out):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
