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
from engine.ingest import InputError, load_bank, load_ledger, load_recon
from engine.llm.client import LLMClient
from engine.llm.narrate import resolve_unknowns
from engine.feegst import fee_gst
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


def _build_report(cfg, lines, recon_rows, index, attributions) -> RunReport:
    ledger = audit_mod.AuditLedger()
    ledger.append("run_start", {"engine_version": _ENGINE_VERSION, "seed": cfg.seed,
                                "provider": cfg.provider_or_none(), "threshold": cfg.threshold,
                                "n_bank_lines": len(lines), "n_recon_rows": len(recon_rows)})
    for a in attributions:
        ledger.append("attribution", {"line_key": a.line_key, "rail": a.rail,
                                      "confidence": round(a.confidence, 4), "tier": a.tier,
                                      "abstained": a.abstained})
    ledger.append("run_end", {"attributed": sum(1 for a in attributions if not a.abstained)})

    by_rail = Counter(a.rail for a in attributions)
    rupees_by_rail: dict[str, int] = defaultdict(int)
    for a, ln in zip(attributions, lines, strict=True):
        rupees_by_rail[a.rail] += ln.amount_paise
    total_credit_paise = sum(ln.amount_paise for ln in lines if ln.is_credit)

    lines_by_key = {ln.key: ln for ln in lines}
    reconciliations, unresolved_rzp, _sidx = reconcile(lines_by_key, attributions, recon_rows)
    feegst = fee_gst(reconciliations, recon_rows)
    reconciled_paise = sum(r.credit_amount_paise for r in reconciliations)

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
        "total_credit_paise": total_credit_paise,
        "required_precision": round(required_precision(), 4),
        "coverage_curve": [c.__dict__ for c in coverage_curve(confidences)],
    }
    return RunReport(
        totals=totals,
        attributions=attributions,
        reconciliations=reconciliations,
        fee_gst=feegst,
        exceptions=[],               # Phase 5 (US3)
        audit_root=ledger.root,
        config={
            "engine_version": _ENGINE_VERSION,
            "seed": cfg.seed,
            "provider": cfg.provider_or_none(),
            "model": cfg.model if cfg.use_ai else None,
            "threshold": cfg.threshold,
        },
    ), ledger


def _cmd_run(args) -> int:
    try:
        cfg = build_config(no_ai=args.no_ai, provider=args.provider, model=args.model,
                           threshold=args.threshold, seed=args.seed)
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 3
    try:
        lines = load_bank(args.bank)
        recon_rows = load_recon(args.recon)
        _ = load_ledger(args.ledger)  # validated; used in later phases
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

    report, _ledger = _build_report(cfg, lines, recon_rows, index, attributions)

    os.makedirs(args.out, exist_ok=True)
    report_path = os.path.join(args.out, "report.json")
    with open(report_path, "w", encoding="utf-8") as fh:
        json.dump(report.to_dict(), fh, sort_keys=True, indent=2, ensure_ascii=False)
        fh.write("\n")
    _ledger.write(os.path.join(args.out, "audit.jsonl"))

    _print_summary(report)
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
    print(f"Total credited: {_fmt_inr(t['total_credit_paise'])} across "
          f"{t['n_recon_rows']} recon rows")
    print(f"Reconciled {_fmt_inr(t['reconciled_paise'])} across {t['reconciled_count']} "
          f"razorpay credits to the paise · {t['unresolved_rzp_count']} unresolved")
    print(f"Recoverable fee-GST (input tax credit, from Razorpay's own tax-on-fee): "
          f"{_fmt_inr(t['fee_gst_recoverable_paise'])}")
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
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="untangle", description="Multi-rail bank-credit attribution.")
    sub = p.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="attribute a batch and write out/report.json")
    run.add_argument("--bank", required=True)
    run.add_argument("--recon", required=True)
    run.add_argument("--ledger", required=True)
    run.add_argument("--out", default="out/")
    run.add_argument("--no-ai", action="store_true")
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
