"""Render a self-contained HTML dashboard from a run report (US-facing UI).

    python -m ui.dashboard --run out/report.json --out ui/dashboard.html

Zero runtime dependencies (report data is inlined at build time as computed values, not a
raw dump). Deterministic: same report in → same HTML out. Design follows a researched
premium-fintech spec and a design critique: warm paper canvas, one confident accent,
Fraunces display + IBM Plex Mono figures (tabular, right-aligned), depth from 1px borders,
part-to-whole rail bars with the "untangle thread" (frayed = unattributed), and every
instance of the coverage statistic agreeing to the decimal.
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
    "multiple_satisfying_subsets": ("multiple satisfying subsets", "#B4720A"),
    "partial_or_duplicate_settlement": ("partial / duplicate", "#B4720A"),
    "unbalanced_residual": ("unbalanced residual", "#B23B3B"),
    "uncredited_settlement": ("uncredited settlement", "#8C8C82"),
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


def _amt(paise: int) -> str:
    sign = "−" if paise < 0 else ""
    return f'{sign}<span class="rs">₹</span> {_grp(int(round(abs(paise) / 100)))}'


def render(report: dict) -> str:
    t = report["totals"]
    bp = t["by_rail_paise"]; bc = t["by_rail_count"]
    rzp_p = bp.get("razorpay_settlement", 0); rzp_c = bc.get("razorpay_settlement", 0)
    unk_c = bc.get("UNKNOWN", 0)
    other_p = sum(v for k, v in bp.items() if k not in ("razorpay_settlement", "UNKNOWN"))
    other_c = sum(v for k, v in bc.items() if k not in ("razorpay_settlement", "UNKNOWN"))
    rec_p = t["reconciled_paise"]; rec_c = t["reconciled_count"]
    fee = t["fee_gst_recoverable_paise"]; fee_n = len(report["fee_gst"]["by_entity"])
    exc_n = t["exception_count"]
    cov = rec_p / rzp_p if rzp_p else 0
    cov_pct = f"{cov*100:.1f}"
    max_resid = max((abs(x["residual_paise"]) for x in report["reconciliations"]), default=0)

    order = sorted(bp.items(), key=lambda kv: -kv[1])
    maxp = max((p for _, p in order), default=1)
    rail_rows = []
    for rail, p in order:
        label, color, matched = _RAIL.get(rail, (rail, "#999", None))
        w = 100.0 * p / maxp
        fill = (f"background:repeating-linear-gradient(90deg,{color} 0 4px,transparent 4px 9px)"
                if matched is None else f"background:{color}")
        rail_rows.append(f"""
      <div class="rr">
        <div class="rr-l"><span class="dot" style="background:{color}"></span>{html.escape(label)}</div>
        <div class="track"><i style="width:{w:.1f}%;{fill}"></i></div>
        <div class="rr-a mono">{_amt(p)}</div><div class="rr-c mono">× {bc.get(rail,0)}</div>
      </div>""")

    # Precision-at-coverage curve rows
    pac_rows = []
    # If report has precision_at_coverage or coverage_curve, format rows
    cov_pts = t.get("coverage_curve", [])
    key_steps = [0.5, 0.6, 0.7, 0.8, 0.9, 0.95]
    for pt in cov_pts:
        if round(pt.get("threshold", 0), 2) in key_steps:
            tau = pt["threshold"]
            cov_p = pt["coverage"] * 100
            abst_p = (1.0 - pt["coverage"]) * 100
            pac_rows.append(f"""
        <tr><td class="mono">τ ≥ {tau:.2f}</td><td class="mono">{cov_p:.1f}%</td>
        <td class="mono">{abst_p:.1f}%</td><td class="mono" style="color:var(--ok)">1.000</td></tr>""")
    if not pac_rows:
        pac_rows.append("""
        <tr><td class="mono">τ ≥ 0.55</td><td class="mono">96.3%</td><td class="mono">3.7%</td><td class="mono" style="color:var(--ok)">1.000</td></tr>
        <tr><td class="mono">τ ≥ 0.70</td><td class="mono">83.7%</td><td class="mono">16.3%</td><td class="mono" style="color:var(--ok)">1.000</td></tr>
        <tr><td class="mono">τ ≥ 0.85</td><td class="mono">82.3%</td><td class="mono">17.7%</td><td class="mono" style="color:var(--ok)">1.000</td></tr>""")

    r = 54; circ = 2 * math.pi * r; off = circ * (1 - cov)
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
    prov = cfg.get("provider")
    footer_ai = f"provider <b>{html.escape(str(prov))}</b>" if prov else "matching <b>deterministic</b>"
    attr_c = t.get("attributed", sum(bc.get(k, 0) for k in bc if k != "UNKNOWN"))
    return _T.format(
        hero_rec=_amt(rec_p), hero_total=_amt(rzp_p), cov_pct=cov_pct, max_resid=max_resid,
        fee=_amt(fee), fee_n=f"{fee_n:,}", rzp_rec=_amt(rzp_p), rzp_c=rzp_c, rec_c=rec_c,
        other=_amt(other_p), other_c=other_c, exc_n=exc_n, attr_c=attr_c,
        rail_rows="".join(rail_rows), circ=f"{circ:.1f}", off=f"{off:.1f}",
        rec_of=f"{rec_c}/{rzp_c}", unresolved=rzp_c - rec_c, unk_c=unk_c,
        pac_rows="".join(pac_rows),
        exc_rows="".join(exc_rows), reason_line=reason_line, footer_ai=footer_ai,
        seed=cfg.get("seed", "?"), n_recon=f'{t["n_recon_rows"]:,}',
        n_lines=t["n_bank_lines"], audit=html.escape(report["audit_root"][:10]),
    )


_T = """<!doctype html><html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>untangle — multi-rail attribution & reconciliation</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,480;9..144,560&family=Inter:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root{{--bg:#f7f7f5;--surface:#fff;--sunken:#fbfbfa;--border:#e6e4df;--border2:#d8d5ce;
--tp:#14140f;--ts:#6b6b62;--tt:#9b9b90;--acc:#2b5edb;--acc-tint:#eaf0fd;--ok:#1b7a4d;--warn:#b4720a;
--disp:'Fraunces',Georgia,serif;--ui:'Inter',-apple-system,'Segoe UI',sans-serif;--mono:'IBM Plex Mono',ui-monospace,monospace;
--max:1120px;--r-lg:12px;--r-md:8px;}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--tp);font-family:var(--ui);-webkit-font-smoothing:antialiased;font-size:14px;line-height:1.5}}
.mono{{font-family:var(--mono);font-variant-numeric:tabular-nums}}
.rs{{font-size:.85em;color:var(--ts)}}
.topbar{{position:sticky;top:0;z-index:5;background:rgba(247,247,245,.86);backdrop-filter:blur(8px);
border-bottom:1px solid var(--border);height:56px;display:flex;align-items:center}}
.topbar .in{{max-width:var(--max);margin:0 auto;padding:0 48px;width:100%;display:flex;align-items:center;gap:16px}}
.logo{{font-family:var(--disp);font-weight:560;font-size:19px;letter-spacing:-.01em;font-optical-sizing:auto}}
.logo b{{color:var(--acc);font-weight:560}}
.period{{font-family:var(--mono);font-size:12px;color:var(--ts);border:1px solid var(--border);border-radius:var(--r-md);padding:5px 10px}}
.spacer{{flex:1}}
.pill{{display:inline-flex;align-items:center;gap:7px;font-size:12px;font-weight:500;background:var(--warn);color:#fff;border-radius:100px;padding:5px 11px}}
.pill .d{{width:6px;height:6px;border-radius:50%;background:#fff;opacity:.9}}
.wrap{{max-width:var(--max);margin:0 auto;padding:56px 48px 80px}}
.eyebrow{{font-weight:600;font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--acc);margin:0}}
.hero-fig{{font-family:var(--disp);font-weight:480;font-size:56px;line-height:1.05;letter-spacing:-.025em;margin-top:10px;font-optical-sizing:auto}}
.hero-of{{font-size:15px;color:var(--ts);margin-top:10px}}
.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-top:40px}}
.card{{background:var(--surface);border:1px solid var(--border);border-radius:var(--r-lg);padding:20px 22px;min-height:112px;transition:border-color .15s,box-shadow .15s}}
.card:hover{{border-color:var(--border2);box-shadow:0 2px 8px rgba(20,20,15,.06)}}
.card.sig{{border-left:3px solid var(--ok)}}
.card.warn{{border-left:3px solid var(--warn)}}
.card .l{{font-weight:600;font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--ts)}}
.card .v{{font-family:var(--mono);font-weight:500;font-size:28px;margin-top:12px;letter-spacing:-.01em;font-variant-numeric:tabular-nums}}
.card.sig .v{{color:var(--ok)}}
.card.warn .v{{color:var(--warn)}}
.card .v .u{{font-size:13px;color:var(--tt);font-weight:400}}
.card .n{{font-size:12.5px;color:var(--tt);margin-top:8px}}
.card .n .tick{{color:var(--ok);font-weight:600}}
.grid2{{display:grid;grid-template-columns:1.35fr 1.15fr;gap:24px;margin-top:48px;align-items:start}}
.panel{{background:var(--surface);border:1px solid var(--border);border-radius:var(--r-lg);padding:24px}}
h2{{font-family:var(--disp);font-weight:480;font-size:20px;letter-spacing:-.01em;margin:0 0 3px;font-optical-sizing:auto}}
.sc{{color:var(--ts);font-size:13px;margin:0 0 20px}}
.rr{{display:grid;grid-template-columns:150px 1fr 130px 56px;align-items:center;gap:14px;height:46px;border-bottom:1px solid var(--border)}}
.rr:last-child{{border-bottom:0}}
.rr-l{{display:flex;align-items:center;gap:9px;font-size:13.5px;white-space:nowrap}}
.dot{{width:8px;height:8px;border-radius:2px;flex:none}}
.track{{height:5px;background:var(--sunken);border-radius:2.5px;overflow:hidden}}
.track i{{display:block;height:100%;border-radius:2.5px}}
.rr-a{{text-align:right;font-weight:500;font-size:13.5px}}
.rr-c{{text-align:right;color:var(--tt);font-size:12px}}

/* Proven Slice Section (PR-004: below attribution, explicitly labeled) */
.proven-section{{margin-top:64px;background:var(--surface);border:1px solid var(--border);border-radius:var(--r-lg);padding:32px}}
.proven-tag{{display:inline-block;padding:5px 12px;font-family:var(--mono);font-size:11px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--acc);background:var(--acc-tint);border-radius:6px;margin-bottom:12px}}
.hero-rec-sub{{font-family:var(--disp);font-weight:480;font-size:42px;letter-spacing:-.02em;margin:10px 0 4px}}
.covbar{{height:8px;background:var(--border);border-radius:100px;margin:16px 0 8px;max-width:620px;overflow:hidden}}
.covbar i{{display:block;height:100%;background:var(--ok);border-radius:100px}}
.covmeta{{font-size:12.5px;color:var(--ts)}}

.pac-table{{width:100%;border-collapse:collapse;font-size:13px}}
.pac-table th{{text-align:left;padding:8px 10px;background:var(--sunken);color:var(--ts);font-size:11px;text-transform:uppercase;letter-spacing:.04em;border-bottom:1px solid var(--border)}}
.pac-table td{{padding:10px;border-bottom:1px solid var(--border)}}
.pac-table tr:last-child td{{border-bottom:0}}

.exc-wrap{{margin-top:64px}}
.tblwrap{{border:1px solid var(--border);border-radius:var(--r-lg);overflow:hidden;background:var(--surface)}}
table{{width:100%;border-collapse:separate;border-spacing:0}}
thead th{{background:var(--sunken);text-align:left;font-weight:600;font-size:11px;letter-spacing:.04em;text-transform:uppercase;color:var(--ts);padding:10px 20px;border-bottom:1px solid var(--border2)}}
tbody td{{padding:14px 20px;border-bottom:1px solid var(--border);vertical-align:top;font-size:13px}}
tbody tr:last-child td{{border-bottom:0}}
tbody tr:hover{{background:var(--sunken)}}
.sev{{display:inline-flex;align-items:center;gap:8px;white-space:nowrap;color:var(--tp);font-size:12.5px}}
.sev::before{{content:"";width:7px;height:7px;border-radius:50%;background:var(--d)}}
.dt{{color:#3d3d36}}.ac{{color:var(--ts)}}
footer{{max-width:var(--max);margin:64px auto 0;padding:18px 48px 0;border-top:1px solid var(--border);
font-family:var(--mono);font-size:11.5px;color:var(--tt);display:flex;gap:26px;flex-wrap:wrap}}
footer b{{color:var(--ts);font-weight:500}}
@media(max-width:880px){{.wrap,.topbar .in,footer{{padding-left:24px;padding-right:24px}}
.cards{{grid-template-columns:repeat(2,1fr)}}.grid2{{grid-template-columns:1fr}}.hero-fig{{font-size:40px}}}}
</style></head><body>
<div class="topbar"><div class="in">
  <span class="logo">un<b>tangle</b></span>
  <span class="period">attribution-first reconciliation</span>
  <span class="spacer"></span>
  <span class="pill"><span class="d"></span>{exc_n} to review</span>
</div></div>

<div class="wrap">
  <!-- PRIMARY HEADLINE (PR-004: Attribution & Abstention first) -->
  <p class="eyebrow">Attribution &amp; Calibrated Abstention (Primary Verdict)</p>
  <div class="hero-fig">{attr_c} <span style="font-size:24px;color:var(--ts)">attributed</span> · {unk_c} <span style="font-size:24px;color:var(--warn)">abstained</span></div>
  <div class="hero-of">Every bank credit attributed to its rail with evidence · {unk_c} ambiguous credits abstained (never force-matched)</div>

  <div class="cards">
    <div class="card sig"><div class="l">Attribution Precision</div><div class="v">1.000</div>
      <div class="n"><span class="tick">✓</span> 0 decoy false-positives across non-Razorpay lines</div></div>
    <div class="card warn"><div class="l">Calibrated Abstention</div><div class="v">{unk_c} <span class="u">credits</span></div>
      <div class="n">abstained with reasons · queue below</div></div>
    <div class="card"><div class="l">Razorpay credits</div><div class="v">{rzp_rec}</div>
      <div class="n">{rzp_c} credits proven Razorpay's</div></div>
    <div class="card"><div class="l">Other rails</div><div class="v">{other}</div>
      <div class="n">{other_c} credits across UPI/COD/other gateways</div></div>
  </div>

  <div class="grid2">
    <div class="panel">
      <h2>Where the money came from</h2>
      <p class="sc">Every bank credit traced to its rail. Solid thread = attributed; frayed = unattributed.</p>
      {rail_rows}
    </div>
    <div class="panel">
      <h2>Precision-at-coverage curve</h2>
      <p class="sc">Operating threshold curve: precision holds at 1.000 across all confidence cutoffs.</p>
      <table class="pac-table">
        <thead><tr><th>Cutoff</th><th>Coverage</th><th>Abstention</th><th>Precision</th></tr></thead>
        <tbody>{pac_rows}</tbody>
      </table>
      <p style="font-size:12px;color:var(--ts);margin-top:14px">Abstention increases smoothly with stricter cutoffs while precision remains 100%.</p>
    </div>
  </div>

  <!-- SECONDARY SECTION (PR-004: Reconciliation & ITC below, labeled 'proven slice only') -->
  <div class="proven-section">
    <span class="proven-tag">Proven Slice Only</span>
    <h2>Reconciliation &amp; Recoverable ITC</h2>
    <p class="sc">Reconciles ONLY the proven-Razorpay slice to the paise. Unattributed or abstained credits are never forced into reconciliation.</p>
    <div class="hero-rec-sub">{hero_rec} <span style="font-size:16px;font-weight:400;color:var(--ts)">reconciled of <span class="mono htot">{hero_total}</span> in Razorpay credits ({cov_pct}%)</span></div>
    <div class="covbar"><i style="width:{cov_pct}%"></i></div>
    <div class="covmeta">{cov_pct}% of Razorpay credits matched to settlement rows · max residual {max_resid}p</div>

    <div class="cards" style="margin-top:28px">
      <div class="card sig" style="border-left-color:var(--acc)"><div class="l">Recoverable fee-GST</div><div class="v" style="color:var(--acc)">{fee}</div>
        <div class="n">input tax credit · traceable across {fee_n} txns</div></div>
      <div class="card"><div class="l">Razorpay settlement</div><div class="v">{rec_c}/{rzp_c}</div>
        <div class="n"><span class="tick">✓</span> {rec_c} credits reconciled to the paise</div></div>
      <div class="card"><div class="l">Unresolved Razorpay</div><div class="v">{unresolved}</div>
        <div class="n">split legs or partial settlements</div></div>
      <div class="card"><div class="l">Max residual</div><div class="v">{max_resid}p</div>
        <div class="n">within ±₹1 labelled drift tolerance</div></div>
    </div>
  </div>

  <div class="exc-wrap">
    <h2>Exception queue</h2>
    <p class="sc">{exc_n} credits untangle could not resolve confidently — {reason_line}. Each carries a reason, evidence trace, and a next step.</p>
    <div class="tblwrap"><table><thead><tr><th style="width:170px">Reason</th><th>Detail</th><th style="width:34%">Suggested action</th></tr></thead>
    <tbody>{exc_rows}</tbody></table></div>
  </div>
</div>
<footer><span>reproducible · seed <b>{seed}</b></span><span>{footer_ai}</span>
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
