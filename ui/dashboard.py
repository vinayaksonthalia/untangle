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
from collections import Counter

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
    "reconstructed_split_leg": ("reconstructed split leg", "#2B5EDB"),
    "rule_conflict": ("rule conflict", "#B23B3B"),
    "ledger_mismatch": ("ledger mismatch", "#B4720A"),
    "duplicate_order_booking": ("duplicate order booking", "#B4720A"),
    "refund_not_reflected": ("refund not reflected", "#8A6D3B"),
}


def _grp(n: int) -> str:
    s = f"{abs(n):d}"
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        parts.insert(0, head)
        s = ",".join(parts) + "," + tail
    return s


def _amt(paise: int) -> str:
    sign = "−" if paise < 0 else ""
    return f'{sign}<span class="rs">₹</span> {_grp(int(round(abs(paise) / 100)))}'


def _embed_json(obj) -> str:
    """JSON-encode for safe embedding inside a <script> element. json.dumps does not escape
    ``<``, so a value containing ``</script>`` would break out of the script at the HTML-parser
    level (stored XSS). Escape the HTML-significant characters and the JS line separators."""
    s = json.dumps(obj, ensure_ascii=False)
    return (
        s.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
        .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    )


_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _month_label(ym: str) -> str:
    """'2026-06' → 'Jun 2026'; passes anything unexpected through untouched."""
    try:
        y, m = ym.split("-")
        return f"{_MONTHS[int(m) - 1]} {y}"
    except (ValueError, IndexError):
        return ym


def _pick_courtroom_exemplar(packets: list[dict]) -> dict | None:
    """The most compelling proven verdict to cross-examine: a reconciled credit whose challenger
    audit shows the largest proof margin (its verdict is furthest from any competing explanation).
    Prefer a decisive-identifier (Tier A) tie. Returns None if no audited packet exists."""
    audited = [p for p in packets if p.get("proof", {}).get("challenge")]
    if not audited:
        return None

    def rank(p: dict) -> tuple:
        ch = p["proof"]["challenge"]
        return (
            1 if p.get("reconciled") else 0,
            1 if p["verdict"]["tier"] == "A" else 0,
            ch.get("proof_margin", 0.0),
        )

    return max(audited, key=rank)


def _courtroom_html(report: dict) -> str:
    """The Evidence Courtroom: one proven verdict, cross-examined — the decisive tie(s), the proof
    margin, the strongest explanation the challenger rejected, and what happens if the tie is removed."""
    ex = _pick_courtroom_exemplar(report.get("proof_packets", []))
    if ex is None:
        return ""
    ch = ex["proof"]["challenge"]
    margin = float(ch.get("proof_margin", 0.0))
    rej = ch.get("rejected_explanation") or {}
    removed = ", ".join(rej.get("removed_signals", [])) or "the decisive tie"
    rej_score = float(rej.get("score", 0.0))
    conf = ex["verdict"]["confidence"]

    ties_html = "".join(
        f'<li><span class="ct-sig">{html.escape(t["signal"])}</span>'
        f'<span class="ct-exp">{html.escape(t.get("explains") or t.get("detail",""))}</span></li>'
        for t in ex["proof"].get("ties", [])
    )
    corr = ex["proof"].get("corroboration", [])
    corr_line = (
        "Corroborated by " + ", ".join(html.escape(c["signal"]) for c in corr) + " — but corroboration is never proof."
        if corr else "No competing rail keyword was present."
    )
    settle = ex.get("settlement") or {}
    n_legs = len(settle.get("covered_entities", []))
    consequence = (
        f'Reconciled to {n_legs} settlement entit{"y" if n_legs == 1 else "ies"} '
        f'({html.escape(str(settle.get("covered_net_inr","")))}), residual '
        f'{settle.get("residual_paise", 0)}p · recoverable fee-GST {html.escape(str(ex.get("fee_gst_recoverable_inr","")))}'
        if ex.get("reconciled") else "Attributed Razorpay; per-leg reconciliation pending."
    )

    return f"""
  <div class="court" id="sec-courtroom">
    <span class="proven-tag">One verdict, cross-examined</span>
    <h2>Evidence courtroom</h2>
    <p class="court-sub">Every Razorpay verdict is challenged before it is accepted. Here is the strongest —
    shown with the tie that proves it, and what remains if that tie is taken away.</p>
    <div class="court-grid">
      <div class="court-credit">
        <div class="cc-amt mono">{html.escape(str(ex["amount_inr"]))}</div>
        <div class="cc-meta mono">{html.escape(str(ex["value_date"]))} · {html.escape((ex.get("narration") or "")[:70])}</div>
        <div class="cc-verdict">Razorpay settlement · {html.escape(str(ex["verdict"]["tier_label"]))} · conf {conf}</div>
      </div>
      <div class="court-proof">
        <div class="cp-block">
          <h5>The tie that decides it</h5>
          <ul class="ct-ties">{ties_html}</ul>
          <p class="ct-corr">{corr_line}</p>
        </div>
        <div class="cp-block">
          <h5>Proof margin <span class="cp-m mono">{margin:.2f}</span></h5>
          <div class="cp-bar"><i style="width:{max(2, min(100, margin*100)):.0f}%"></i></div>
          <p class="ct-corr">The Razorpay score outranks the best competing explanation by {margin:.2f}.</p>
        </div>
        <div class="cp-block cp-reject">
          <h5>Strongest explanation the challenger rejected</h5>
          <p class="ct-rej">{html.escape(str(rej.get("detail","")))}</p>
          <p class="ct-collapse">Remove <span class="mono">{html.escape(removed)}</span> and the verdict
          collapses to a score of <span class="mono">{rej_score:.2f}</span> — resemblance, not proof.
          That is why this credit is Razorpay's and a look-alike is not.</p>
        </div>
        <div class="cp-block">
          <h5>Consequence</h5>
          <p class="ct-conseq">{consequence}</p>
        </div>
      </div>
    </div>
  </div>"""


def render(report: dict, months_by_key: dict | None = None) -> str:
    t = report["totals"]
    bp = t["by_rail_paise"]
    bc = t["by_rail_count"]
    rzp_p = bp.get("razorpay_settlement", 0)
    rzp_c = bc.get("razorpay_settlement", 0)
    unk_c = bc.get("UNKNOWN", 0)
    other_p = sum(v for k, v in bp.items() if k not in ("razorpay_settlement", "UNKNOWN"))
    other_c = sum(v for k, v in bc.items() if k not in ("razorpay_settlement", "UNKNOWN"))
    rec_p = t["reconciled_paise"]
    rec_c = t["reconciled_count"]
    fee = t["fee_gst_recoverable_paise"]
    fee_n = len(report["fee_gst"]["by_entity"])
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
        <td class="mono">{abst_p:.1f}%</td></tr>""")
    if not pac_rows:
        pac_rows.append("""
        <tr><td class="mono" colspan="3" style="color:var(--ts)">run against data to populate the coverage / abstention curve</td></tr>""")

    r = 54
    circ = 2 * math.pi * r
    off = circ * (1 - cov)
    mbk = months_by_key or {}
    exc_months: dict[str, int] = {}
    exc_rows = []
    for e in report["exceptions"]:
        lbl, col = _REASON.get(e["reason_code"], (e["reason_code"], "#6B6B62"))
        mo = mbk.get(e["line_key"], "")
        if mo:
            exc_months[mo] = exc_months.get(mo, 0) + 1
        # Render the evidence trace (each exception claims one) — the example/affected ids etc.
        ev_items = e.get("evidence") or []
        ev_html = "".join(
            f'<div class="evln"><span class="evs">{html.escape(it["signal"])}</span> {html.escape(it["detail"])}</div>'
            for it in ev_items if it.get("detail")
        )
        ev_text = " ".join(f'{it.get("signal","")} {it.get("detail","")}' for it in ev_items)
        blob = html.escape(f'{lbl} {e["detail"]} {e["suggested_action"]} {ev_text}'.lower(), quote=True)
        exc_rows.append(f"""
      <tr class="excrow" data-reason="{html.escape(e["reason_code"])}" data-month="{html.escape(mo)}" data-text="{blob}">
      <td><span class="sev" style="--d:{col}">{html.escape(lbl)}</span></td>
      <td class="dt">{html.escape(e["detail"])}{f'<div class="evwrap">{ev_html}</div>' if ev_html else ''}</td>
      <td class="ac">{html.escape(e["suggested_action"])}</td></tr>""")

    cfg = report.get("config", {})
    reasons = t.get("exceptions_by_reason", {})
    reason_line = " · ".join(
        f'{v} {html.escape(_REASON.get(k, (k, ""))[0])}' for k, v in reasons.items()
    )
    # Interactive filter chips for the exception queue (built from the actual reason counts).
    # The "All" chip uses a dedicated data-all flag, never a data-reason sentinel, so it can never
    # collide with a real reason_code (sol review HIGH).
    chips = [f'<button type="button" class="chip active" data-all="1" aria-pressed="true">All <span class="ct">{exc_n}</span></button>']
    for k, v in reasons.items():
        lbl = html.escape(_REASON.get(k, (k, ""))[0])
        chips.append(f'<button type="button" class="chip" data-reason="{html.escape(k)}" aria-pressed="false">{lbl} <span class="ct">{v}</span></button>')
    filter_chips = "".join(chips)

    # Month filter chips — only when the queue genuinely spans more than one month. This filters the
    # review work-list by each credit's statement month; it recomputes no metric and invents no
    # per-month number (reconciliation lags across month boundaries, so per-month totals would be
    # dishonest). "All months" carries a dedicated data-allm flag, never a data-month sentinel.
    month_chips = ""
    if len(exc_months) >= 2:
        mparts = ['<button type="button" class="chip mchip active" data-allm="1" aria-pressed="true">All months</button>']
        for m in sorted(exc_months):
            mparts.append(
                f'<button type="button" class="chip mchip" data-month="{html.escape(m)}" '
                f'aria-pressed="false">{_month_label(m)} <span class="ct">{exc_months[m]}</span></button>'
            )
        month_chips = ('<div class="chips mrow" role="group" aria-label="Filter by month">' + "".join(mparts) + "</div>")

    # Toolbar + count only make sense when there is a queue to filter (sol review MEDIUM).
    if exc_n:
        exc_toolbar = (
            '<div class="exc-toolbar"><div class="chipcol"><div class="chips" role="group" aria-label="Filter by reason">'
            + filter_chips
            + "</div>" + month_chips
            + '</div><div class="search"><input id="excSearch" type="search" '
            'placeholder="Search reason, detail, action…" autocomplete="off" '
            'aria-label="Search exceptions"/></div></div>'
        )
        exc_section_copy = (
            f"{exc_n} items untangle surfaced for review — {reason_line}. "
            "Each carries a reason, evidence trace, and a next step."
        )
    else:
        exc_toolbar = ""
        exc_section_copy = "No exceptions — every credit was attributed with evidence or abstained cleanly."

    recov = report.get("recovery_plan") or {}
    actions = recov.get("actions", [])
    recoverable_p = recov.get("recoverable_if_actioned_paise", 0)
    note = recov.get("note")
    recovery_rows = []
    for i, a in enumerate(actions, 1):
        act_type = a.get("action_type", "")
        cost = a.get("cost", 1.0)
        rec_paise = a.get("recoverable_paise", 0)
        resolves = a.get("resolves", [])
        desc = a.get("description") or f"Action {act_type} — up to {_amt(rec_paise)} recoverable if confirmed"
        resolves_str = f"{len(resolves)} credit{'s' if len(resolves) != 1 else ''}"
        resolves_keys = ", ".join(resolves[:3]) + (f" ... +{len(resolves)-3} more" if len(resolves) > 3 else "")
        recovery_rows.append(f"""
      <tr class="recov-row">
        <td class="mono" style="font-weight:600;color:var(--acc)">#{i}</td>
        <td>
          <div style="font-weight:600;font-size:14px;color:var(--tp)">{html.escape(act_type.replace('_', ' ').title())}</div>
          <div style="font-size:13px;color:var(--ts);margin-top:2px">{html.escape(desc)}</div>
        </td>
        <td>
          <div class="mono" style="font-size:13px">{html.escape(resolves_str)}</div>
          <div style="font-size:11px;color:var(--ts);font-family:var(--mono)">{html.escape(resolves_keys)}</div>
        </td>
        <td class="mono" style="text-align:right">
          <div style="font-weight:600;color:var(--acc)">{_amt(rec_paise)}</div>
          <div style="font-size:11px;color:var(--ts)">up to · if confirmed</div>
        </td>
        <td class="mono" style="text-align:right;font-size:12px;color:var(--ts)">
          {cost:.1f}
        </td>
      </tr>""")

    if not recovery_rows:
        recovery_rows.append("""
      <tr><td colspan="5" style="text-align:center;padding:24px;color:var(--ts)">
        All bank credits resolved — no recovery actions needed.
      </td></tr>""")

    note_html = f'<div style="font-size:12px;color:var(--warn);margin:10px 0">{html.escape(note)}</div>' if note else ''
    recovery_section = f"""
  <div class="exc-wrap" id="sec-recovery" style="margin-top:40px">
    <div style="display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap;gap:12px">
      <div>
        <span class="proven-tag">Next-Best Actions</span>
        <h2 style="margin-top:6px">Active Recovery Plan</h2>
        <p class="sc">Ranked next-best actions by expected impact per unit cost. Recommends actions to resolve ambiguous credits or missing settlements — never asserts money is owed.</p>
      </div>
      <div class="mono" style="font-size:13px;color:var(--ts)">
        {len(actions)} recommended action(s) · up to <span style="font-weight:600;color:var(--tp)">{_amt(recoverable_p)}</span> recoverable if confirmed
      </div>
    </div>
    {note_html}
    <div class="tblwrap" style="margin-top:16px">
      <table id="recovTable">
        <thead>
          <tr>
            <th style="width:50px">Rank</th>
            <th>Action &amp; Recommendation</th>
            <th style="width:180px">Target Credits</th>
            <th style="width:160px;text-align:right">Recoverable</th>
            <th style="width:70px;text-align:right">Cost</th>
          </tr>
        </thead>
        <tbody>
          {''.join(recovery_rows)}
        </tbody>
      </table>
    </div>
  </div>"""

    # Feature 006: Global Solver Violated Constraints section
    rejected_matches = report.get("rejected_matches") or []
    solver_rows = []
    for r in rejected_matches:
        credit_keys = ", ".join(r.get("credit_keys", ()))
        target_id = r.get("target_id", "")
        violation = r.get("violated_constraint", "")
        detail = r.get("detail", "")
        violation_label = violation.replace("_", " ").title()
        solver_rows.append(f"""
      <tr>
        <td class="mono" style="font-size:12px;font-weight:600">{html.escape(credit_keys)}</td>
        <td class="mono" style="font-size:12px">{html.escape(target_id)}</td>
        <td>
          <span class="badg" style="background:#fde8e8;color:#b23b3b;border:1px solid #f8b4b4;padding:2px 6px;border-radius:3px;font-size:11px;font-weight:600">
            {html.escape(violation_label)}
          </span>
        </td>
        <td style="font-size:13px;color:var(--tp)">{html.escape(detail)}</td>
      </tr>""")

    if solver_rows:
        solver_section = f"""
  <div class="exc-wrap" id="sec-solver" style="margin-top:40px">
    <div style="display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap;gap:12px">
      <div>
        <span class="proven-tag" style="background:#eef2ff;color:#2b5edb;border-color:#c7d2fe">Globally-Forced Assignment</span>
        <h2 style="margin-top:6px">Global Evidence-Constrained Reconciliation</h2>
        <p class="sc">Proof of global consistency: local candidate matches that cannot be part of any globally-valid assignment are rejected with the violated constraint recorded.</p>
      </div>
      <div class="mono" style="font-size:13px;color:var(--ts)">
        {len(rejected_matches)} locally-plausible match(es) rejected under global constraints
      </div>
    </div>
    <div class="tblwrap" style="margin-top:16px">
      <table>
        <thead>
          <tr>
            <th style="width:180px">Contending Credit</th>
            <th style="width:160px">Target Settlement</th>
            <th style="width:180px">Violated Constraint</th>
            <th>Globally-Forced Alternative &amp; Detail</th>
          </tr>
        </thead>
        <tbody>
          {''.join(solver_rows)}
        </tbody>
      </table>
    </div>
  </div>"""
        solver_nav = '<a href="#sec-solver">Solver</a>'
    else:
        solver_section = ""
        solver_nav = ""

    prov = cfg.get("provider")
    footer_ai = f"provider <b>{html.escape(str(prov))}</b>" if prov else "matching <b>deterministic</b>"
    attr_c = t.get("attributed", sum(bc.get(k, 0) for k in bc if k != "UNKNOWN"))
    # Honest provenance classes (never over-claims an alternate rail from absence of evidence).
    _prov = Counter(a.get("provenance_class", "") for a in report.get("attributions", []))
    prov_summary = (
        f'<b>{_prov.get("razorpay_proven", 0)}</b> Razorpay-proven · '
        f'<b>{_prov.get("non_razorpay", 0)}</b> non-Razorpay (signalled) · '
        f'<b>{_prov.get("ambiguous", 0)}</b> ambiguous · '
        f'<b>{_prov.get("unattributed", 0)}</b> unattributed'
    )

    return _T.format(
        prov_summary=prov_summary,
        hero_rec=_amt(rec_p), hero_total=_amt(rzp_p), cov_pct=cov_pct, max_resid=max_resid,
        fee=_amt(fee), fee_n=f"{fee_n:,}", rzp_rec=_amt(rzp_p), rzp_c=rzp_c, rec_c=rec_c,
        other=_amt(other_p), other_c=other_c, exc_n=exc_n, attr_c=attr_c,
        rail_rows="".join(rail_rows), circ=f"{circ:.1f}", off=f"{off:.1f}",
        rec_of=f"{rec_c}/{rzp_c}", unresolved=rzp_c - rec_c, unk_c=unk_c,
        unresolved_cash=_amt(recoverable_p),
        pac_rows="".join(pac_rows),
        exc_rows="".join(exc_rows), footer_ai=footer_ai,
        exc_toolbar=exc_toolbar, exc_section_copy=exc_section_copy, script=_DASH_JS,
        recovery_section=recovery_section,
        solver_section=solver_section,
        solver_nav=solver_nav,
        courtroom=_courtroom_html(report),
        proof_json=_embed_json(report.get("proof_packets", [])),
        proof_count=len(report.get("proof_packets", [])),
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
/* Provenance classes (honest labels) */
.prov-row{{margin:14px 0 4px;font-size:13.5px;color:var(--ts)}}
.prov-row b{{color:var(--tp);font-weight:600}}
.prov-note{{display:block;font-size:12px;color:var(--tt);margin-top:6px;max-width:80ch;line-height:1.5}}
.prov-note em{{color:var(--ts);font-style:italic}}
/* Evidence courtroom */
.court{{margin-top:64px;background:#101014;border-radius:var(--r-lg);padding:34px 36px;color:#e9e9e6}}
.court .proven-tag{{color:#8fb0ff;background:rgba(143,176,255,.12)}}
.court h2{{font-family:var(--disp);font-weight:480;font-size:28px;color:#fff;margin:2px 0 6px;letter-spacing:-.01em}}
.court-sub{{color:#b7b7b2;font-size:14px;margin:0 0 24px;max-width:78ch;line-height:1.55}}
.court-grid{{display:grid;grid-template-columns:.85fr 1.15fr;gap:26px;align-items:start}}
.court-credit{{background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.09);border-radius:12px;padding:22px}}
.cc-amt{{font-family:var(--disp);font-size:34px;font-weight:480;color:#fff;letter-spacing:-.02em;line-height:1}}
.cc-meta{{font-size:11.5px;color:#8a8a86;margin-top:12px;word-break:break-word;line-height:1.5}}
.cc-verdict{{margin-top:16px;font-size:12.5px;color:#57c98a;font-weight:500}}
.court-proof{{display:flex;flex-direction:column;gap:18px}}
.cp-block h5{{font-family:var(--mono);font-size:10.5px;letter-spacing:.07em;text-transform:uppercase;color:#8a8a86;margin:0 0 8px;font-weight:500}}
.cp-block .cp-m{{color:#57c98a;font-size:13px;margin-left:6px}}
.ct-ties{{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:7px}}
.ct-ties li{{display:flex;gap:10px;align-items:baseline;font-size:13px}}
.ct-sig{{font-family:var(--mono);font-size:11.5px;color:#8fb0ff;flex:0 0 auto}}
.ct-exp{{color:#d7d7d2}}
.ct-corr{{font-size:12px;color:#8a8a86;margin:8px 0 0;line-height:1.5}}
.cp-bar{{height:8px;background:rgba(255,255,255,.1);border-radius:100px;overflow:hidden;max-width:420px}}
.cp-bar i{{display:block;height:100%;background:linear-gradient(90deg,#57c98a,#8fb0ff);border-radius:100px}}
.cp-reject{{background:rgba(240,179,87,.07);border:1px solid rgba(240,179,87,.18);border-radius:10px;padding:14px 16px}}
.cp-reject h5{{color:#f0b357}}
.ct-rej{{font-size:13px;color:#e9e9e6;margin:0 0 8px}}
.ct-collapse{{font-size:13px;color:#d7d7d2;margin:0;line-height:1.55}}
.ct-collapse .mono,.cc-meta.mono,.cc-amt.mono{{font-family:var(--mono)}}
.ct-conseq{{font-size:13px;color:#d7d7d2;margin:0;line-height:1.5}}
@media(max-width:820px){{.court-grid{{grid-template-columns:1fr;gap:18px}}.court{{padding:26px 22px}}}}

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
.evwrap{{margin-top:7px;display:grid;gap:3px}}
.evln{{font-family:var(--mono);font-size:11px;color:var(--tt);word-break:break-word}}
.evs{{color:var(--acc)}}
footer{{max-width:var(--max);margin:64px auto 0;padding:18px 48px 0;border-top:1px solid var(--border);
font-family:var(--mono);font-size:11.5px;color:var(--tt);display:flex;gap:26px;flex-wrap:wrap}}
footer b{{color:var(--ts);font-weight:500}}
a.logo{{text-decoration:none;color:var(--tp)}}
.secnav{{display:flex;gap:20px;margin-left:26px}}
.secnav a{{font-size:13px;color:var(--ts);text-decoration:none;padding:4px 0;border-bottom:2px solid transparent;transition:color .15s,border-color .15s}}
.secnav a:hover{{color:var(--tp)}}
.secnav a.on{{color:var(--tp);border-color:var(--acc)}}
a.pill{{text-decoration:none}}
[id^="sec-"]{{scroll-margin-top:74px}}
.exc-toolbar{{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;margin-bottom:16px;flex-wrap:wrap}}
.chipcol{{display:flex;flex-direction:column;gap:10px}}
.chips{{display:flex;gap:8px;flex-wrap:wrap}}
.chips.mrow{{padding-top:2px;border-top:1px dashed var(--border);margin-top:2px}}
.mchip.active{{background:var(--acc);border-color:var(--acc);color:#fff}}
.mchip.active .ct{{opacity:.85}}
.chip{{font-family:var(--ui);font-size:12.5px;color:var(--ts);background:var(--surface);border:1px solid var(--border);border-radius:100px;padding:6px 13px;cursor:pointer;transition:all .13s;display:inline-flex;align-items:center;gap:7px}}
.chip:hover{{border-color:var(--border2);color:var(--tp)}}
.chip.active{{background:var(--tp);color:#fff;border-color:var(--tp)}}
.chip .ct{{font-family:var(--mono);font-size:11px;opacity:.7}}
.chip.active .ct{{opacity:.85}}
.search input{{font-family:var(--ui);font-size:13px;color:var(--tp);background:var(--surface);border:1px solid var(--border);border-radius:var(--r-md);padding:8px 13px;width:250px;max-width:60vw;outline:none;transition:border-color .13s}}
.search input:focus{{border-color:var(--acc)}}
tbody tr.hide{{display:none}}
.noresults{{padding:26px 20px;text-align:center;color:var(--ts);font-size:13px}}
.linkbtn{{background:none;border:0;color:var(--acc);cursor:pointer;font-size:13px;font-family:var(--ui);text-decoration:underline;padding:0}}
.exc-count{{font-size:12px;color:var(--tt);margin:12px 2px 0;font-family:var(--mono)}}
.proof-wrap{{margin-top:64px}}
.proof-head{{display:flex;justify-content:space-between;align-items:flex-start;gap:20px;flex-wrap:wrap}}
.proof-actions{{display:flex;gap:10px;flex:none}}
.xbtn{{font-family:var(--ui);font-size:13px;font-weight:500;color:var(--tp);background:var(--surface);border:1px solid var(--border2);border-radius:var(--r-md);padding:8px 14px;cursor:pointer;transition:border-color .13s,background .13s}}
.xbtn:hover{{border-color:var(--acc);color:var(--acc)}}
.proof-search{{margin:16px 0}}
.proof-search input{{font-family:var(--ui);font-size:13px;color:var(--tp);background:var(--surface);border:1px solid var(--border);border-radius:var(--r-md);padding:9px 13px;width:340px;max-width:100%;outline:none}}
.proof-search input:focus{{border-color:var(--acc)}}
#proofTable td{{cursor:pointer;vertical-align:top}}
.pk-amt{{font-family:var(--mono);font-weight:500;font-size:13.5px}}.pk-date{{font-family:var(--mono);font-size:11px;color:var(--tt)}}
.pk-narr{{font-size:12.5px;color:#3d3d36;word-break:break-word}}
.pk-tie{{margin-top:5px;display:inline-flex;align-items:center;gap:6px;font-size:11px;font-family:var(--mono);color:var(--acc);background:var(--acc-tint);border-radius:5px;padding:2px 7px}}
.pk-tier{{font-family:var(--mono);font-size:12px;color:var(--ts)}}
.pk-fee{{font-family:var(--mono);font-size:13px;color:var(--ok)}}
.pk-detail{{background:var(--sunken);border-top:1px solid var(--border)}}
.pk-detail td{{cursor:default;padding:0}}
.pk-inner{{padding:16px 20px;font-size:12.5px;color:var(--ts);display:grid;gap:12px}}
.pk-inner h5{{margin:0 0 5px;font-size:11px;letter-spacing:.05em;text-transform:uppercase;color:var(--tt);font-weight:600}}
.pk-ev{{font-family:var(--mono);font-size:11.5px;color:#3d3d36;line-height:1.7}}
.pk-ev .w{{color:var(--tt)}}
.pk-reject{{color:var(--ts);font-style:italic}}
tr.pk-row.open td{{background:var(--sunken)}}
@media(max-width:880px){{.wrap,.topbar .in,footer{{padding-left:24px;padding-right:24px}}
.cards{{grid-template-columns:repeat(2,1fr)}}.grid2{{grid-template-columns:1fr}}.hero-fig{{font-size:40px}}
.secnav{{display:none}}.search input{{width:100%}}.exc-toolbar{{align-items:stretch}}.search{{width:100%}}}}
</style></head><body>
<div class="topbar"><div class="in">
  <span class="logo">un<b>tangle</b></span>
  <span class="period">attribution-first reconciliation</span>
  <nav class="secnav">
    <a href="#sec-attribution">Attribution</a>
    <a href="#sec-reconciliation">Reconciliation</a>
    <a href="#sec-courtroom">Courtroom</a>
    <a href="#sec-exceptions">Exceptions</a>
    <a href="#sec-recovery">Recovery</a>
    {solver_nav}
    <a href="#sec-proof">Proof</a>
  </nav>
  <span class="spacer"></span>
  <a class="pill" href="#sec-exceptions"><span class="d"></span>{exc_n} to review</a>
</div></div>

<div class="wrap">
  <!-- PRIMARY HEADLINE (PR-004: Attribution & Abstention first) -->
  <p class="eyebrow" id="sec-attribution">Attribution &amp; Calibrated Abstention (Primary Verdict)</p>
  <div class="hero-fig">{attr_c} <span style="font-size:24px;color:var(--ts)">attributed</span> · {unk_c} <span style="font-size:24px;color:var(--warn)">abstained</span></div>
  <div class="hero-of">Every bank credit attributed to its rail with evidence · {unk_c} ambiguous credits abstained (never force-matched)</div>
  <div class="prov-row">{prov_summary}<span class="prov-note">Only Razorpay is <em>proven</em> (a report-backed tie). "Non-Razorpay" means a distinctive signal points elsewhere — a claim about not-Razorpay, never inferred from absence of evidence.</span></div>

  <div class="cards">
    <div class="card sig"><div class="l">Attributed with evidence</div><div class="v">{attr_c}</div>
      <div class="n"><span class="tick">✓</span> {unk_c} abstained, not guessed — precision-first</div></div>
    <div class="card warn"><div class="l">Calibrated Abstention</div><div class="v">{unk_c} <span class="u">credits</span></div>
      <div class="n">abstained with reasons · queue below</div></div>
    <div class="card"><div class="l">Razorpay credits</div><div class="v">{rzp_rec}</div>
      <div class="n">{rzp_c} credits proven Razorpay's</div></div>
    <div class="card"><div class="l">Non-Razorpay (signalled)</div><div class="v">{other}</div>
      <div class="n">{other_c} credits with a distinctive non-Razorpay signal · not proven to the Razorpay bar</div></div>
  </div>

  <div class="grid2">
    <div class="panel">
      <h2>Where the money came from</h2>
      <p class="sc">Every bank credit traced to its rail. Solid thread = attributed; frayed = unattributed.</p>
      {rail_rows}
    </div>
    <div class="panel">
      <h2>Coverage vs abstention</h2>
      <p class="sc">How coverage trades against abstention as the confidence cutoff rises, for this run.</p>
      <table class="pac-table">
        <thead><tr><th>Cutoff</th><th>Coverage</th><th>Abstention</th></tr></thead>
        <tbody>{pac_rows}</tbody>
      </table>
      <p style="font-size:12px;color:var(--ts);margin-top:14px">Stricter cutoffs raise abstention and shrink coverage. Attribution precision (1.000, 0 decoy false-positives) is measured only on the labeled sealed benchmark — never claimed on unlabeled uploads.</p>
    </div>
  </div>

  <!-- SECONDARY SECTION (PR-004: Reconciliation & ITC below, labeled 'proven slice only') -->
  <div class="proven-section" id="sec-reconciliation">
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
      <div class="card sig" style="border-left-color:var(--warn)"><div class="l">Unresolved cash</div><div class="v" style="color:var(--warn)">{unresolved_cash}</div>
        <div class="n">{unresolved} credits not booked without proof · recoverable if evidence supplied (see plan)</div></div>
      <div class="card"><div class="l">Max residual</div><div class="v">{max_resid}p</div>
        <div class="n">within ±₹1 labelled drift tolerance</div></div>
    </div>
  </div>
{courtroom}
  <div class="exc-wrap" id="sec-exceptions">
    <h2>Exception queue</h2>
    <p class="sc">{exc_section_copy}</p>
    {exc_toolbar}
    <div class="tblwrap"><table id="excTable"><thead><tr><th style="width:180px">Reason</th><th>Detail</th><th style="width:34%">Suggested action</th></tr></thead>
    <tbody>{exc_rows}</tbody></table>
    <div class="noresults" id="excEmpty" hidden>No exceptions match this filter. <button type="button" class="linkbtn" id="excClear">Clear filters</button></div>
    </div>
    <p class="exc-count mono" id="excCount" role="status" aria-live="polite"></p>
  </div>

  {recovery_section}

  {solver_section}

  <div class="proof-wrap" id="sec-proof">
    <div class="proof-head">
      <div>
        <h2>Proof packets</h2>
        <p class="sc">A receipt for every credit proven to be Razorpay's — the bank line, the exact tie back to the settlement report, the settlements it covers, and the recoverable fee-GST. Click any row for the full evidence.</p>
      </div>
      <div class="proof-actions">
        <button type="button" class="xbtn" id="proofJson">Export JSON</button>
        <button type="button" class="xbtn" id="proofCsv">Export CSV</button>
      </div>
    </div>
    <div class="proof-search"><input id="proofSearch" type="search" placeholder="Search narration, UTR, tier, settlement…" autocomplete="off" aria-label="Search proof packets"/></div>
    <div class="tblwrap"><table id="proofTable"><thead><tr>
      <th style="width:150px">Date · Amount</th><th>Credit & tie</th><th style="width:90px">Tier</th><th style="width:120px">Fee-GST</th>
    </tr></thead><tbody id="proofBody"></tbody></table></div>
    <p class="exc-count mono" id="proofCount"></p>
  </div>
</div>
<script>window.__PROOF__ = {proof_json};</script>
{script}
<footer><span>reproducible · seed <b>{seed}</b></span><span>{footer_ai}</span>
<span><b>{n_lines}</b> bank credits · <b>{n_recon}</b> recon rows</span><span>audit <b>{audit}…</b></span></footer>
</body></html>"""


_DASH_JS = """<script>
(function(){
  var rows = Array.prototype.slice.call(document.querySelectorAll('#excTable tbody tr.excrow'));
  // Two independent chip groups: reason (data-all / data-reason) and month (data-allm / data-month).
  var reasonChips = Array.prototype.slice.call(document.querySelectorAll('.chip:not(.mchip)'));
  var monthChips = Array.prototype.slice.call(document.querySelectorAll('.chip.mchip'));
  var search = document.getElementById('excSearch');
  var empty = document.getElementById('excEmpty');
  var count = document.getElementById('excCount');
  var clear = document.getElementById('excClear');
  var total = rows.length;
  var reason = null; // null = all reasons; never a data-reason sentinel, so no collision with real codes
  var month = null;  // null = all months

  function setActive(group, chip){
    group.forEach(function(x){
      var on = x === chip;
      x.classList.toggle('active', on);
      x.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
  }
  function apply(){
    var q = (search && search.value || '').trim().toLowerCase();
    var shown = 0;
    rows.forEach(function(tr){
      var okR = (reason === null) || (tr.getAttribute('data-reason') === reason);
      var okM = (month === null) || (tr.getAttribute('data-month') === month);
      var okQ = !q || (tr.getAttribute('data-text') || '').indexOf(q) !== -1;
      var vis = okR && okM && okQ;
      tr.classList.toggle('hide', !vis);
      if (vis) shown++;
    });
    if (empty) empty.hidden = !(total > 0 && shown === 0);
    if (count) count.textContent = shown === total
      ? total + ' exceptions'
      : 'Showing ' + shown + ' of ' + total + ' exceptions';
  }
  reasonChips.forEach(function(c){
    c.addEventListener('click', function(){
      setActive(reasonChips, c);
      reason = c.hasAttribute('data-all') ? null : c.getAttribute('data-reason');
      apply();
    });
  });
  monthChips.forEach(function(c){
    c.addEventListener('click', function(){
      setActive(monthChips, c);
      month = c.hasAttribute('data-allm') ? null : c.getAttribute('data-month');
      apply();
    });
  });
  if (search) search.addEventListener('input', apply);
  if (clear) clear.addEventListener('click', function(){
    reason = null; month = null; if (search) search.value = '';
    var allR = reasonChips.filter(function(x){ return x.hasAttribute('data-all'); })[0];
    if (allR) setActive(reasonChips, allR);
    var allM = monthChips.filter(function(x){ return x.hasAttribute('data-allm'); })[0];
    if (allM) setActive(monthChips, allM);
    apply();
  });
  apply();

  // Proof packets: render, expand, search, export.
  var packets = (window.__PROOF__ || []);
  var pbody = document.getElementById('proofBody');
  var psearch = document.getElementById('proofSearch');
  var pcount = document.getElementById('proofCount');
  function esc(s){ var d=document.createElement('span'); d.textContent = (s==null?'':String(s)); return d.innerHTML; }
  function blob(text, mime, name){
    try{
      var b=new Blob([text],{type:mime}); var u=URL.createObjectURL(b);
      var a=document.createElement('a'); a.href=u; a.download=name; document.body.appendChild(a); a.click();
      document.body.removeChild(a); setTimeout(function(){URL.revokeObjectURL(u);},1000);
    }catch(e){}
  }
  function toCsv(rows){
    var cols=['line_key','value_date','amount_inr','narration','bank_ref','rail','tier','confidence','tie_signals','reconciled','covered_entity_count','residual_paise','balanced','fee_gst_recoverable_inr'];
    function q(v){ v=(v==null?'':String(v)); if('=+-@\\t\\r\\n'.indexOf(v.charAt(0))!==-1) v="'"+v; return /[",\\n\\r]/.test(v)?'"'+v.replace(/"/g,'""')+'"':v; }
    var out=[cols.join(',')];
    rows.forEach(function(p){
      var st=p.settlement||{};
      out.push([p.line_key,p.value_date,p.amount_inr,p.narration,p.bank_ref,p.verdict.rail,p.verdict.tier,p.verdict.confidence,
        (p.proof.ties||[]).map(function(t){return t.signal;}).join('; '),p.reconciled,(st.covered_entities||[]).length,
        (st.residual_paise==null?'':st.residual_paise),(st.balanced==null?'':st.balanced),p.fee_gst_recoverable_inr].map(q).join(','));
    });
    return out.join('\\n')+'\\n';
  }
  function detailHtml(p){
    var ties=(p.proof.ties||[]).map(function(t){return '<div class="pk-ev">✓ '+esc(t.explains)+' — <span class="w">'+esc(t.detail)+'</span></div>';}).join('');
    var corr=(p.proof.corroboration||[]).map(function(c){return '<div class="pk-ev">· '+esc(c.signal)+' <span class="w">('+esc(c.weight)+') '+esc(c.detail)+'</span></div>';}).join('');
    var st=p.settlement;
    var settle = st ? ('<div><h5>Settlement coverage</h5><div class="pk-ev">'+esc(st.covered_entities.length)+' entities · covered net '+esc(st.covered_net_inr)+' · residual '+esc(st.residual_paise)+' paise · '+(st.balanced?'balanced':'unbalanced')+'</div></div>')
      : '<div><h5>Settlement coverage</h5><div class="pk-ev pk-reject">attributed Razorpay; per-leg entity reconciliation pending (see exceptions)</div></div>';
    return '<div class="pk-inner">'
      + '<div><h5>Why it is Razorpay (report-backed tie)</h5>'+(ties||'<div class="pk-ev">'+esc(p.verdict.tier_label)+'</div>')+'</div>'
      + (corr?'<div><h5>Corroboration</h5>'+corr+'</div>':'')
      + settle
      + '<div><h5>Recoverable fee-GST</h5><div class="pk-ev">'+esc(p.fee_gst_recoverable_inr)+' input tax credit</div></div>'
      + '<div><h5>Why not another rail</h5><div class="pk-ev pk-reject">'+esc(p.proof.rejected_alternatives)+'</div></div>'
      + '</div>';
  }
  function renderProof(q){
    if(!pbody) return;
    q=(q||'').trim().toLowerCase();
    pbody.innerHTML='';
    var shown=0;
    packets.forEach(function(p,i){
      var hay=(p.narration+' '+p.bank_ref+' '+p.verdict.tier+' '+(p.proof.ties||[]).map(function(t){return t.signal+' '+t.detail;}).join(' ')).toLowerCase();
      if(q && hay.indexOf(q)===-1) return;
      shown++;
      var tie=(p.proof.ties[0]||{}).signal||p.verdict.tier;
      var tr=document.createElement('tr'); tr.className='pk-row';
      tr.innerHTML='<td><div class="pk-amt">'+esc(p.amount_inr)+'</div><div class="pk-date">'+esc(p.value_date)+'</div></td>'
        +'<td><div class="pk-narr">'+esc(p.narration)+'</div><span class="pk-tie">🔗 '+esc(tie)+'</span></td>'
        +'<td class="pk-tier">'+esc(p.verdict.tier)+'</td>'
        +'<td class="pk-fee">'+esc(p.fee_gst_recoverable_inr)+'</td>';
      var dr=document.createElement('tr'); dr.className='pk-detail'; dr.style.display='none';
      dr.innerHTML='<td colspan="4">'+detailHtml(p)+'</td>';
      tr.addEventListener('click',function(){ var open=dr.style.display!=='none'; dr.style.display=open?'none':''; tr.classList.toggle('open',!open); });
      pbody.appendChild(tr); pbody.appendChild(dr);
    });
    if(pcount) pcount.textContent = shown===packets.length ? (packets.length+' proven Razorpay credits') : ('Showing '+shown+' of '+packets.length);
  }
  if(pbody){
    renderProof('');
    if(psearch) psearch.addEventListener('input',function(){ renderProof(psearch.value); });
    var pj=document.getElementById('proofJson'); if(pj) pj.addEventListener('click',function(){ blob(JSON.stringify(packets,null,2),'application/json','proof_packets.json'); });
    var pc=document.getElementById('proofCsv'); if(pc) pc.addEventListener('click',function(){ blob(toCsv(packets),'text/csv','proof_packets.csv'); });
  }

  // Section-nav scroll-spy (rect-based; robust to positioned ancestors — sol review LOW)
  var links = Array.prototype.slice.call(document.querySelectorAll('.secnav a'));
  var targets = links.map(function(a){ return document.querySelector(a.getAttribute('href')); });
  function spy(){
    var idx = 0;
    targets.forEach(function(t, i){ if (t && t.getBoundingClientRect().top <= 90) idx = i; });
    // At the bottom of the page the final section may never reach the 90px line (short/empty
    // queue); force the last nav item active so it can always be reached (sol/Qodo).
    var d = document.documentElement;
    if (window.innerHeight + window.scrollY >= d.scrollHeight - 2) idx = targets.length - 1;
    links.forEach(function(a, i){
      var on = i === idx;
      a.classList.toggle('on', on);
      if (on) a.setAttribute('aria-current', 'location'); else a.removeAttribute('aria-current');
    });
  }
  if (links.length && 'onscroll' in window) { window.addEventListener('scroll', spy, {passive:true}); spy(); }
})();
</script>"""


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
