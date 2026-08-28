"""untangle CLI (contracts/cli.md).

Commands:
  run   attribute → report over one batch (MVP: attribution sections)
  why   print the stored trace for one line_key

Exit codes: 0 success · 2 input/validation error · 3 config error. Never a bare
stack trace — all known failure modes are caught and reported human-readably.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict

from engine import audit as audit_mod
from engine.abstain import coverage_curve, required_precision
from engine.attribute import attribute_all
from engine.config import ConfigError, build_config
from engine.evidence import ReconIndex
from engine.exceptions import build_exceptions
from engine.feegst import fee_gst
from engine.ingest import InputError, load_bank, load_ledger, load_recon
from engine.llm.client import LLMClient
from engine.llm.narrate import resolve_unknowns
from engine.models import Rail, RunReport
from engine.reconcile import reconcile

_ENGINE_VERSION = "0.1.0"


def _fmt_inr(paise: int) -> str:
    rupees = paise / 100.0
    # Indian grouping (lakh/crore) on the integer part.
    neg = rupees < 0
    s = f"{abs(int(round(rupees))):d}"
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        parts.insert(0, head)
        s = ",".join(parts) + "," + tail
    return ("-" if neg else "") + "₹" + s


def build_report(cfg, lines, recon_rows, index, attributions, order_ledger=None,
                 *, with_recovery: bool = True) -> RunReport:
    ledger = audit_mod.AuditLedger()
    ledger.append("run_start", {"engine_version": _ENGINE_VERSION, "seed": cfg.seed,
                                "provider": cfg.provider_or_none(), "threshold": cfg.threshold,
                                "n_bank_lines": len(lines), "n_recon_rows": len(recon_rows)})
    for a in attributions:
        ledger.append("attribution", {"line_key": a.line_key, "rail": a.rail,
                                      "confidence": round(a.confidence, 4), "tier": a.tier,
                                      "abstained": a.abstained})
    by_rail = Counter(a.rail for a in attributions)
    rupees_by_rail: dict[str, int] = defaultdict(int)
    for a, ln in zip(attributions, lines, strict=True):
        rupees_by_rail[a.rail] += ln.amount_paise
    total_credit_paise = sum(ln.amount_paise for ln in lines if ln.is_credit)

    lines_by_key = {ln.key: ln for ln in lines}
    reconciliations, unresolved_rzp, sidx = reconcile(lines_by_key, attributions, recon_rows)
    feegst = fee_gst(reconciliations, recon_rows)
    reconciled_paise = sum(r.credit_amount_paise for r in reconciliations)
    exceptions = build_exceptions(
        attributions,
        unresolved_rzp,
        lines_by_key,
        ambiguous_rzp=sidx.ambiguous_lines,
        duplicate_or_split_rzp=sidx.duplicate_or_split_lines,
        unbalanced_rzp=sidx.unbalanced_lines,
    )
    # Feature 003: order-ledger reconciliation is ADDITIVE — it only appends new exceptions and
    # never touches any attribution/reconciliation verdict or metric above.
    if order_ledger:
        from engine.ledger import reconcile_ledger
        exceptions = exceptions + reconcile_ledger(order_ledger, reconciliations, recon_rows)
    for r in reconciliations:
        ledger.append("reconciliation", {"line_key": r.line_key,
                                         "covered": len(r.covered_entity_ids),
                                         "residual_paise": r.residual_paise, "balanced": r.balanced})
    for e in exceptions:
        ledger.append("exception", {"line_key": e.line_key, "reason_code": e.reason_code})
    ledger.append("run_end", {"attributed": sum(1 for a in attributions if not a.abstained),
                              "reconciled": len(reconciliations), "exceptions": len(exceptions)})

    confidences = [a.confidence for a in attributions if not a.abstained]
    totals = {
        "n_bank_lines": len(lines),
        "n_recon_rows": len(recon_rows),
        "by_rail_count": dict(sorted(by_rail.items())),
        "by_rail_paise": dict(sorted(rupees_by_rail.items())),
        "attributed": sum(1 for a in attributions if not a.abstained),
        "abstained": sum(1 for a in attributions if a.abstained),
        "reconciled_count": len(reconciliations),
        "reconciled_paise": reconciled_paise,
        "unresolved_rzp_count": len(unresolved_rzp),
        "fee_gst_recoverable_paise": feegst.total_recoverable_paise,
        "exception_count": len(exceptions),
        "exceptions_by_reason": dict(sorted(Counter(e.reason_code for e in exceptions).items())),
        "total_credit_paise": total_credit_paise,
        "required_precision": round(required_precision(), 4),
        # Honest denominator: coverage is over ALL lines, so abstentions lower it (a run that
        # abstains on half its lines must not report 100% coverage of the other half).
        "coverage_curve": [c.__dict__ for c in coverage_curve(confidences, total=len(attributions))],
    }
    from engine.proof import build_proof_packets
    from engine.recovery import build_recovery_plan

    # Additive post-pass: computed only when enabled, so a report built with_recovery=False is byte-identical
    # to the pre-Feature-005 report (the additivity property test relies on this to compare both builds).
    recovery_plan = build_recovery_plan(lines, attributions, index, exceptions) if with_recovery else None
    proof_packets = build_proof_packets(lines, attributions, reconciliations, recon_rows, feegst)
    return RunReport(
        totals=totals,
        attributions=attributions,
        reconciliations=reconciliations,
        fee_gst=feegst,
        exceptions=exceptions,
        proof_packets=proof_packets,
        audit_root=ledger.root,
        config={
            "engine_version": _ENGINE_VERSION,
            "seed": cfg.seed,
            "provider": cfg.provider_or_none(),
            "model": cfg.model if cfg.use_ai else None,
            "threshold": cfg.threshold,
        },
        recovery_plan=recovery_plan,
    ), ledger


def _cmd_run(args) -> int:
    try:
        cfg = build_config(no_ai=not args.ai, provider=args.provider, model=args.model,
                           threshold=args.threshold, seed=args.seed)
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 3
    try:
        lines = load_bank(args.bank)
        recon_rows = load_recon(args.recon)
        order_ledger = load_ledger(args.ledger)  # Feature 003: cross-checked against the proven slice
    except InputError as exc:
        print(f"Input error: {exc}", file=sys.stderr)
        return 2

    index = ReconIndex(recon_rows)
    attributions = attribute_all(lines, index, cfg.threshold)

    if cfg.use_ai:
        client = LLMClient(enabled=True, provider=cfg.provider, model=cfg.model,
                           api_key=cfg.api_key)
        lines_by_key = {ln.key: ln for ln in lines}
        attributions = resolve_unknowns(attributions, lines_by_key, index, client)

    report, _ledger = build_report(cfg, lines, recon_rows, index, attributions, order_ledger)

    os.makedirs(args.out, exist_ok=True)
    report_path = os.path.join(args.out, "report.json")
    with open(report_path, "w", encoding="utf-8") as fh:
        json.dump(report.to_dict(), fh, sort_keys=True, indent=2, ensure_ascii=False)
        fh.write("\n")
    _ledger.write(os.path.join(args.out, "audit.jsonl"))

    # Proof Packets: the per-credit evidence receipts, exported for a finance team / CA.
    from engine.proof import proof_packets_to_csv
    with open(os.path.join(args.out, "proof_packets.json"), "w", encoding="utf-8") as fh:
        json.dump(report.proof_packets, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    with open(os.path.join(args.out, "proof_packets.csv"), "w", encoding="utf-8") as fh:
        fh.write(proof_packets_to_csv(report.proof_packets))

    _print_summary(report)
    print(f"Proof packets: {len(report.proof_packets)} written to "
          f"{os.path.join(args.out, 'proof_packets.json')} (+ .csv)")
    return 0


def _print_summary(report: RunReport) -> None:
    t = report.totals
    counts = t["by_rail_count"]
    rzp = counts.get(Rail.RAZORPAY_SETTLEMENT.value, 0)
    unknown = counts.get(Rail.UNKNOWN.value, 0)
    other = t["attributed"] - rzp
    print(f"Attributed {t['n_bank_lines']} lines: "
          f"{rzp} razorpay · {other} other-rail · {unknown} UNKNOWN (abstained)")
    for rail in sorted(counts):
        print(f"    {rail:<22} {counts[rail]:>4}   {_fmt_inr(t['by_rail_paise'].get(rail, 0))}")
    if "coverage_curve" in t:
        key_thresholds = [0.5, 0.6, 0.7, 0.8, 0.9, 0.95]
        curve_pts = [p for p in t["coverage_curve"] if round(p["threshold"], 2) in key_thresholds]
        if curve_pts:
            print("Attribution & Abstention Curve (threshold sweep):")
            for p in curve_pts:
                cov = p["coverage"] * 100
                abst = (1.0 - p["coverage"]) * 100
                print(f"    τ ≥ {p['threshold']:.2f}: coverage {cov:>5.1f}% · abstention {abst:>5.1f}%")
    print(f"Total credited: {_fmt_inr(t['total_credit_paise'])} across "
          f"{t['n_recon_rows']} recon rows")
    print(f"Reconciled {_fmt_inr(t['reconciled_paise'])} across {t['reconciled_count']} "
          f"razorpay credits to the paise (±₹1 labelled drift) · {t['unresolved_rzp_count']} unresolved")
    print(f"Recoverable fee-GST (input tax credit, from Razorpay's own tax-on-fee): "
          f"{_fmt_inr(t['fee_gst_recoverable_paise'])}")
    by_reason = ", ".join(f"{k} {v}" for k, v in t.get("exceptions_by_reason", {}).items())
    print(f"Exceptions: {t.get('exception_count', 0)}" + (f" ({by_reason})" if by_reason else ""))
    if report.recovery_plan and report.recovery_plan.actions:
        plan = report.recovery_plan
        recov_inr = _fmt_inr(plan.recoverable_if_actioned_paise)
        print(f"Active Recovery Plan: {len(plan.actions)} action(s) · up to {recov_inr} recoverable if confirmed")
        for i, act in enumerate(plan.actions[:3], 1):
            print(f"    {i}. {act.description}")
        if len(plan.actions) > 3:
            print(f"    ... ({len(plan.actions) - 3} more action(s) in report.json)")
    print(f"Audit root: {report.audit_root}")


def _cmd_why(args) -> int:
    report_path = os.path.join(args.out, "report.json")
    try:
        with open(report_path, encoding="utf-8") as fh:
            report = json.load(fh)
    except FileNotFoundError:
        print(f"Input error: no report at {report_path}. Run `untangle run` first.",
              file=sys.stderr)
        return 2
    match = next((a for a in report["attributions"] if a["line_key"] == args.line_key), None)
    if match is None:
        print(f"Input error: line_key {args.line_key!r} not found in {report_path}.",
              file=sys.stderr)
        return 2
    print(f"line_key : {match['line_key']}")
    print(f"rail     : {match['rail']}  (confidence {match['confidence']}, tier {match['tier']})")
    print(f"abstained: {match['abstained']}   llm_used: {match['llm_used']}")
    print("evidence :")
    if not match["evidence"]:
        print("    (none — insufficient signal, abstained)")
    for e in match["evidence"]:
        print(f"    - [{e['weight']:.2f}] {e['signal']}: {e['detail']}")
    rec = next((r for r in report.get("reconciliations", []) if r["line_key"] == args.line_key), None)
    if rec:
        print(f"reconciled: covers {len(rec['covered_entity_ids'])} recon rows; "
              f"residual {rec['residual_paise']} paise; balanced={rec['balanced']}")
    exc = next((e for e in report.get("exceptions", []) if e["line_key"] == args.line_key), None)
    if exc:
        print(f"exception: {exc['reason_code']} — {exc['detail']}")
        print(f"    suggested: {exc['suggested_action']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="untangle", description="Multi-rail bank-credit attribution.")
    sub = p.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="attribute a batch and write out/report.json")
    run.add_argument("--bank", required=True)
    run.add_argument("--recon", required=True)
    run.add_argument("--ledger", required=True)
    run.add_argument("--out", default="out/")
    # AI is OFF by default (G4): the deterministic core is the shipped default. Opt in with --ai.
    run.add_argument("--ai", action="store_true",
                     help="enable the edge LLM narration tier (OFF by default)")
    # Backward-compat: older docs/scripts pass --no-ai; AI is already off by default, so it is a no-op.
    run.add_argument("--no-ai", action="store_true", help=argparse.SUPPRESS)
    run.add_argument("--provider", choices=["openrouter", "gemini", "groq", "cerebras"])
    run.add_argument("--model")
    run.add_argument("--threshold", type=float, default=None)
    run.add_argument("--seed", type=int, default=42)
    run.set_defaults(func=_cmd_run)

    why = sub.add_parser("why", help="explain one credit's verdict")
    why.add_argument("line_key")
    why.add_argument("--out", default="out/")
    why.set_defaults(func=_cmd_why)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
