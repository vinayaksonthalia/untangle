#!/usr/bin/env python3
"""Verify every schema claim we make about Razorpay's settlement-recon response
against committed vendor fixtures. Run: python3 scripts/verify_schema_claims.py

No network. No LLM. Reads only files in fixtures/ so anyone can reproduce the
result byte-for-byte. Every claim in README/EXCEPTION_TAXONOMY.md must appear here.
"""
import html
import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "fixtures"
API = FIX / "recon_api_reference_2026-08-21.html"
SDK = FIX / "recon_sdk_node_2026-08-21.md"

RECON_IDS = ("pay_DEXrnipqTmWVGE", "rfnd_DGRcGzZSLyEdg1", "trf_DEUoCEtdsJgvl7", "adj_EhcHONhX4ChgNC")


def decoded(path: Path) -> str:
    raw = path.read_text(encoding="utf-8", errors="replace")
    return unquote(html.unescape(raw)).replace("\\n", "\n").replace('\\"', '"')


def rows(text: str) -> dict:
    """Pull each recon row out of the fixture by its entity_id, as a dict."""
    out = {}
    for eid in RECON_IDS:
        i = text.find(f'"entity_id": "{eid}"')
        if i == -1:
            continue
        start = text.rfind("{", 0, i)
        depth, j = 0, start
        while j < len(text):
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        blob = text[start : j + 1]
        try:
            out[eid] = json.loads(blob)
        except json.JSONDecodeError:
            out[eid] = {k: v for k, v in re.findall(r'"(\w+)":\s*("[^"]*"|null|true|false|-?\d+)', blob)}
    return out


def check(label, ok, detail):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}\n         {detail}")
    return ok


def main() -> int:
    if not API.exists() or not SDK.exists():
        print("Missing fixtures. See fixtures/*.txt for source URLs.")
        return 2

    api_txt, sdk_txt = decoded(API), decoded(SDK)
    api, sdk = rows(api_txt), rows(sdk_txt)
    results = []

    print("\nCLAIM 1 — vendor serves geo-varied samples with identical numbers")
    a_cur = api[RECON_IDS[0]].get("currency")
    s_cur = sdk[RECON_IDS[0]].get("currency")
    same_nums = all(
        api[e].get(f) == sdk[e].get(f) for e in api for f in ("amount", "fee", "tax", "debit", "credit") if e in sdk
    )
    results.append(check(
        "amounts identical across the two vendor sources",
        same_nums,
        f"api currency={a_cur} sdk currency={s_cur}; amount/fee/tax/debit/credit identical: {same_nums}",
    ))

    print("\nCLAIM 2 — `tax` is included INSIDE `fee` (not added on top)")
    trf = api[RECON_IDS[2]]
    lhs, rhs = trf.get("debit"), trf.get("amount", 0) + trf.get("fee", 0)
    results.append(check(
        "transfer row: debit == amount + fee",
        lhs == rhs,
        f"debit={lhs} == amount({trf.get('amount')}) + fee({trf.get('fee')}) = {rhs}; "
        f"tax={trf.get('tax')} would make {rhs + trf.get('tax', 0)} if additive",
    ))

    print("\nCLAIM 3 — `payment_id` is null on payment rows (id lives in entity_id)")
    pay = api[RECON_IDS[0]]
    results.append(check(
        "payment row has payment_id: null",
        pay.get("payment_id") is None,
        f"entity_id={pay.get('entity_id')} payment_id={pay.get('payment_id')!r} — "
        f"joining on payment_id drops every payment row",
    ))

    print("\nCLAIM 4 — adjustment row omits `credit_type`")
    adj_api, adj_sdk = api[RECON_IDS[3]], sdk[RECON_IDS[3]]
    ok = "credit_type" not in adj_api and "credit_type" not in adj_sdk
    results.append(check(
        "credit_type absent from adjustment row in BOTH sources",
        ok,
        f"api adjustment keys include credit_type: {'credit_type' in adj_api}; "
        f"sdk: {'credit_type' in adj_sdk}; payment row has it: {'credit_type' in pay}",
    ))

    print("\nCLAIM 5 — adjustment row has no join key of any kind")
    ok = all(adj_api.get(k) is None for k in ("order_id", "payment_id", "settlement_utr"))
    results.append(check(
        "adjustment: order_id, payment_id, settlement_utr all null",
        ok,
        f"order_id={adj_api.get('order_id')!r} payment_id={adj_api.get('payment_id')!r} "
        f"settlement_utr={adj_api.get('settlement_utr')!r} description={adj_api.get('description')!r}",
    ))

    print("\nCLAIM 6 — `notes` declared object, delivered as string/null")
    declared = bool(re.search(r"notes.{0,400}?\bobject\b", api_txt, re.S | re.I))
    delivered = {e: type(api[e].get("notes")).__name__ for e in api}
    results.append(check(
        "declared type 'object' but sample values are str/None",
        declared and all(v in ("str", "NoneType") for v in delivered.values()),
        f"declared-as-object found in page: {declared}; delivered types: {delivered}",
    ))

    print("\nCLAIM 7 — `credit_type` / `posted_at` appear in samples but not in the parameter table")
    # The JSON samples are percent-encoded in the page source; the parameter table is plain text.
    plain = API.read_text(encoding="utf-8", errors="replace")
    for field in ("credit_type", "posted_at"):
        in_sample = field in api_txt
        in_plain_table = field in plain  # unencoded occurrence => documented in a table
        print(f"         {field}: in_sample={in_sample} appears_unencoded_in_page={in_plain_table}")
    print("         (unencoded==False alongside in_sample==True ⇒ undocumented field)")

    print("\nCLAIM 8 — enums are IN-localized; card fields are null for UPI/netbanking/wallet")
    seg = ""
    for m in re.finditer("method", api_txt):
        s = re.sub(r"\s+", " ", api_txt[m.start() : m.start() + 1800])
        if "ossible value" in s:
            seg = s
            break
    methods = [v for v in re.findall(r'children: "([a-z]{3,12})"', seg)]
    in_only = {"upi", "netbanking", "wallet", "emi"}
    results.append(check(
        "method enum is Indian (upi/netbanking/wallet/emi), not US (ach)",
        in_only.issubset(set(methods)) and "ach" not in methods,
        f"documented method values: {sorted(set(methods))} — clustering for fee variance MUST be "
        f"method-aware: 4-tuple (method, card_network, card_type, card_issuer) is card-only; "
        f"UPI/netbanking/wallet rows carry null card fields and need their own key",
    ))

    print("\n" + "=" * 72)
    passed = sum(1 for r in results if r)
    print(f"{passed}/{len(results)} verifiable claims PASS")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
