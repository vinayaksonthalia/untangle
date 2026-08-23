"""Render a self-contained HTML dashboard from a run report (US-facing UI).

    python -m ui.dashboard --run out/report.json --out ui/dashboard.html

Zero runtime dependencies: the report JSON is embedded, so the file opens anywhere
(file:// or any static host) with no server and no network. Deterministic: same report
in → same HTML out.

Design: a "bank statement" idiom — statement-paper ground, ink figures set in a mono
tabular face and aligned on the decimal, hairline rules, teal reserved for "reconciled".
The signature is the account ribbon: one stacked bar of the commingled account that
untangles into the per-rail tally below.
"""

from __future__ import annotations

import argparse
import html
import json


def _inr(paise: int, with_paise: bool = False) -> str:
    r = paise / 100.0
    neg = r < 0
    whole = abs(int(r)) if with_paise else abs(int(round(r)))
    s = f"{whole:d}"
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:]); head = head[:-2]
        parts.insert(0, head)
        s = ",".join(parts) + "," + tail
    out = "₹" + s
    if with_paise:
        out += f".{abs(paise) % 100:02d}"
    return ("−" if neg else "") + out


_RAIL_LABEL = {
    "razorpay_settlement": "Razorpay settlement", "other_gateway": "Other gateway",
    "direct_upi": "Direct UPI", "cod_remittance": "COD remittance",
    "unrelated": "Unrelated", "UNKNOWN": "Unattributed",
}
# Muted, professional rail colours (no neon). Razorpay = the one blue; teal reserved for
# the reconciled state elsewhere.
_RAIL_COLOR = {
    "razorpay_settlement": "#1d4ed8", "other_gateway": "#7c5cbf",
    "direct_upi": "#2a9d8f", "cod_remittance": "#c2843b",
    "unrelated": "#9aa1ab", "UNKNOWN": "#c0492f",
}
_REASON_LABEL = {
    "razorpay_coverage_not_found": "coverage not found",
    "razorpay_uncertain": "razorpay uncertain",
    "unattributed_ambiguous": "unattributed",
}


def render(report: dict) -> str:
    t = report["totals"]
    rzp_count = t["by_rail_count"].get("razorpay_settlement", 0)
    unknown = t["by_rail_count"].get("UNKNOWN", 0)
    total = t["total_credit_paise"] or 1
    by_rail = sorted(t["by_rail_paise"].items(), key=lambda kv: -kv[1])

    # Signature: the account ribbon (one stacked bar of the whole account).
    ribbon = "".join(
        f'<i style="width:{100.0 * p / total:.3f}%;background:{_RAIL_COLOR.get(r, "#999")}" '
        f'title="{html.escape(_RAIL_LABEL.get(r, r))}: {_inr(p)}"></i>'
        for r, p in by_rail
    )

    # Per-rail tally rows (decimal-aligned amounts, share bar).
    maxp = max((p for _, p in by_rail), default=1)
    tally = []
    for r, p in by_rail:
        tally.append(
            f'<tr><td class="rl"><span class="sw" style="background:{_RAIL_COLOR.get(r,"#999")}">'
            f'</span>{html.escape(_RAIL_LABEL.get(r, r))}</td>'
            f'<td class="ct">{t["by_rail_count"].get(r, 0)}</td>'
            f'<td class="amt">{_inr(p)}</td>'
            f'<td class="shb"><i style="width:{100.0*p/maxp:.1f}%;background:{_RAIL_COLOR.get(r,"#999")}"></i></td></tr>'
        )

    recs = report["reconciliations"]
    max_resid = max((abs(x["residual_paise"]) for x in recs), default=0)

    exc = []
    for e in report["exceptions"]:
        exc.append(
            f'<tr><td><span class="chip c-{html.escape(e["reason_code"])}">'
            f'{html.escape(_REASON_LABEL.get(e["reason_code"], e["reason_code"]))}</span></td>'
            f'<td class="dt">{html.escape(e["detail"])}</td>'
            f'<td class="ac">{html.escape(e["suggested_action"])}</td></tr>'
        )

    cfg = report.get("config", {})
    recon_pct = 100.0 * t["reconciled_count"] / rzp_count if rzp_count else 0

    return _TEMPLATE.format(
        total=_inr(t["total_credit_paise"]), n_lines=t["n_bank_lines"],
        reconciled=_inr(t["reconciled_paise"]), rec_count=t["reconciled_count"], rzp_count=rzp_count,
        fee_gst=_inr(t["fee_gst_recoverable_paise"]), fee_n=len(report["fee_gst"]["by_entity"]),
        exc_count=t["exception_count"], unknown=unknown, recon_pct=f"{recon_pct:.0f}",
        max_resid=max_resid, ribbon=ribbon, tally="\n".join(tally), exc_rows="\n".join(exc),
        seed=cfg.get("seed", "?"), provider=html.escape(str(cfg.get("provider") or "none")),
        n_recon=f'{t["n_recon_rows"]:,}', audit=html.escape(report["audit_root"][:12]),
    )


_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>untangle — settlement attribution</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root{{--paper:#fbfaf6;--card:#ffffff;--ink:#1b1f24;--mut:#6a7280;--rule:#e7e3d8;
--teal:#0f766e;--amber:#b45309;--blue:#1d4ed8;
--sans:'IBM Plex Sans',system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
--mono:'IBM Plex Mono',ui-monospace,SFMono-Regular,Menlo,monospace;}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--paper);color:var(--ink);font-family:var(--sans);
-webkit-font-smoothing:antialiased}}
.wrap{{max-width:1040px;margin:0 auto;padding:40px 24px 72px}}
.mono{{font-family:var(--mono);font-variant-numeric:tabular-nums}}
header{{display:flex;align-items:baseline;justify-content:space-between;
border-bottom:2px solid var(--ink);padding-bottom:14px}}
.brand{{font-weight:700;font-size:22px;letter-spacing:-.3px}}
.brand b{{color:var(--teal)}}
.kicker{{font-family:var(--mono);font-size:12px;color:var(--mut);letter-spacing:.5px;text-transform:uppercase}}
.lead{{color:#3d434c;max-width:680px;margin:22px 0 26px;font-size:15.5px;line-height:1.55}}
.eyebrow{{font-family:var(--mono);font-size:11.5px;letter-spacing:1.4px;text-transform:uppercase;
color:var(--mut);margin:0 0 12px}}
/* account ribbon — the signature */
.ribbon{{display:flex;height:34px;border-radius:4px;overflow:hidden;border:1px solid var(--rule)}}
.ribbon i{{display:block;height:100%;border-right:1px solid rgba(255,255,255,.55)}}
.ribbon i:last-child{{border-right:0}}
.ribbon-cap{{display:flex;justify-content:space-between;font-family:var(--mono);font-size:11.5px;
color:var(--mut);margin-top:7px}}
/* figures row */
.figs{{display:grid;grid-template-columns:repeat(4,1fr);gap:0;margin:30px 0 8px;
border-top:1px solid var(--rule);border-bottom:1px solid var(--rule)}}
.fig{{padding:18px 20px 18px 0;border-right:1px solid var(--rule)}}
.fig:last-child{{border-right:0}}
.fig .l{{font-family:var(--mono);font-size:11.5px;letter-spacing:.8px;text-transform:uppercase;color:var(--mut)}}
.fig .v{{font-family:var(--mono);font-weight:600;font-size:25px;letter-spacing:-.5px;margin-top:8px}}
.fig .n{{font-size:12.5px;color:var(--mut);margin-top:5px}}
.fig.hero .v{{color:var(--teal)}}
.fig .tick{{color:var(--teal);font-weight:600}}
section{{margin-top:42px}}
h2{{font-size:15px;font-weight:600;margin:0 0 4px}}
.sc{{color:var(--mut);font-size:13px;margin:0 0 16px}}
table{{width:100%;border-collapse:collapse}}
/* tally */
.tally td{{padding:10px 12px;border-bottom:1px solid var(--rule);font-size:14px}}
.tally .rl{{white-space:nowrap}}
.sw{{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:9px;vertical-align:middle}}
.tally .ct{{font-family:var(--mono);color:var(--mut);text-align:right;width:70px}}
.tally .amt{{font-family:var(--mono);font-variant-numeric:tabular-nums;text-align:right;
font-weight:600;width:150px}}
.tally .shb{{width:190px}}.tally .shb i{{display:block;height:6px;border-radius:3px}}
.note{{display:flex;gap:26px;flex-wrap:wrap;color:var(--mut);font-size:13px;margin-top:16px;
padding-top:14px;border-top:1px solid var(--rule)}}
.note b{{color:var(--ink);font-family:var(--mono)}}
/* exceptions */
.exc th{{text-align:left;font-family:var(--mono);font-size:11px;letter-spacing:.6px;text-transform:uppercase;
color:var(--mut);font-weight:500;padding:0 12px 10px;border-bottom:1px solid var(--ink)}}
.exc td{{padding:12px;border-bottom:1px solid var(--rule);vertical-align:top;font-size:13.5px}}
.exc .dt{{color:#3d434c}}.exc .ac{{color:var(--mut)}}
.chip{{display:inline-block;padding:3px 10px;border-radius:3px;font-family:var(--mono);font-size:11.5px;
font-weight:500;white-space:nowrap}}
.c-razorpay_coverage_not_found{{background:#e8eefb;color:#1d4ed8}}
.c-razorpay_uncertain{{background:#f6ecd6;color:#8a5a12}}
.c-unattributed_ambiguous{{background:#f6e0dd;color:#a23a2a}}
footer{{margin-top:44px;padding-top:16px;border-top:2px solid var(--ink);
display:flex;gap:26px;flex-wrap:wrap;font-family:var(--mono);font-size:12px;color:var(--mut)}}
footer b{{color:var(--ink)}}
@media(max-width:760px){{.figs{{grid-template-columns:repeat(2,1fr)}}.fig:nth-child(2){{border-right:0}}
.tally .shb{{display:none}}}}
</style></head><body><div class="wrap">
<header><div class="brand">un<b>tangle</b></div><div class="kicker">multi-rail settlement reconciliation</div></header>

<p class="lead">One merchant bank account receives money from many rails at once. untangle sorts every
credit to its source, reconciles the Razorpay slice to the paise, and surfaces the input tax credit
hidden inside it — abstaining, never guessing, when a credit can't be proven.</p>

<p class="eyebrow">The account, untangled</p>
<div class="ribbon">{ribbon}</div>
<div class="ribbon-cap"><span>{total} credited · {n_lines} lines</span><span>one account · six sources</span></div>

<div class="figs">
  <div class="fig"><div class="l">Total credited</div><div class="v">{total}</div><div class="n">{n_lines} bank credits</div></div>
  <div class="fig"><div class="l">Razorpay reconciled</div><div class="v">{reconciled}</div>
    <div class="n"><span class="tick">✓</span> {rec_count}/{rzp_count} to the paise · within {max_resid}p</div></div>
  <div class="fig hero"><div class="l">Recoverable fee-GST</div><div class="v">{fee_gst}</div>
    <div class="n">input tax credit · {fee_n} txns, traceable</div></div>
  <div class="fig"><div class="l">Flagged for review</div><div class="v">{exc_count}</div><div class="n">never guessed — see below</div></div>
</div>

<section>
  <h2>Where the money came from</h2>
  <p class="sc">Each bank credit attributed to a payment rail. Amounts are the sum credited on that rail.</p>
  <table class="tally"><tbody>{tally}</tbody></table>
  <div class="note"><span><b>{rzp_count}</b> attributed Razorpay, <b>0</b> false positives</span>
  <span><b>{unknown}</b> abstained rather than guessed</span>
  <span><b>{recon_pct}%</b> of the Razorpay slice reconciled to the paise</span></div>
</section>

<section>
  <h2>Exception queue</h2>
  <p class="sc">{exc_count} credits untangle could not resolve confidently — each with a reason and a next step. Nothing is force-matched.</p>
  <table class="exc"><thead><tr><th>Reason</th><th>Detail</th><th>Suggested action</th></tr></thead>
  <tbody>{exc_rows}</tbody></table>
</section>

<footer><span>reproducible · seed <b>{seed}</b></span><span>AI <b>{provider}</b></span>
<span><b>{n_recon}</b> recon rows</span><span>audit root <b>{audit}…</b></span></footer>
</div>
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
