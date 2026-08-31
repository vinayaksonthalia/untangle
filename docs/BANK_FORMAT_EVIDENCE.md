# Bank-Format Support Matrix & Evidence Classification

**Repository:** `vinayaksonthalia/untangle`  
**Purpose:** Truth-and-evidence audit establishing the exact support status, provenance, and verification level of bank formats across Untangle.

---

## 1. Support Level Taxonomy

Untangle evaluates bank format support across six precise, non-collapsible tiers. A generic "supported" status is never used.

| Level | Tier Name | Definition & Entry Criteria | Ingestion & Verification Status |
|---|---|---|---|
| **Level 1** | **Unsupported** | No adapter exists and no compatible verified fixture exists. | Raw export cannot be parsed. |
| **Level 2** | **Narration represented** | Synthetic or adversarial narrations mention the bank or imitate its clearing grammar. | Narration string rules exist in evidence weighting; native file format cannot be parsed. |
| **Level 3** | **Generic-schema compatible** | A CSV file uses column headers accepted by `GenericCsvBankAdapter` (e.g. `Date,Narration,Credit,Debit` after alias normalization). | File parses via the generic adapter, but compatibility with the named bank's proprietary export layout is unproven. |
| **Level 4** | **Format fixture validated** | A sanitized authentic export or a structurally equivalent fixture derived from authoritative documentation exists in the repo with recorded provenance. | Parsing unit tests cover metadata rows, headers, dates, monetary values, and line numbering. |
| **Level 5** | **Dedicated adapter validated** | A named, dedicated adapter class exists in `engine/bank_adapters.py` with unambiguous structural detection. | Authentic and adversarial test suites pass; adapter is registered or available in registry. |
| **Level 6** | **End-to-end validated** | The bank format runs through full ingestion, attribution, reconciliation, exceptions, journal export, and close certificate verification. | Precision, recall, coverage, and limitations are measured and reported. |

---

## 2. Bank Format Evidence Matrix

The table below documents the verified state of bank formats in Untangle today.

| Bank / Institution | Format Description | Current Support Level | Adapter ID | Fixture Path | Test Path | Source / Provenance Status | Demonstrated Capabilities | Undemonstrated Capabilities | Next Required Evidence |
|---|---|---|---|---|---|---|---|---|---|
| **Generic Untangle CSV** | Standard canonical CSV (`value_date`, `narration`, `credit`, `debit`, optional `ref_no`) | **Level 6: End-to-end validated** | `generic_csv` (v1.0.0) | `data/bank_statement.csv`<br>`fixtures/bank_statement_ood.csv` | `tests/unit/test_bank_adapters.py`<br>`tests/unit/test_ingest_bank_formats.py` | Untangle canonical schema specification | Structural detection, date parsing, paise conversion, directionality, deduplication, full reconciliation & journal export | Ingestion of raw proprietary columns not mapped in generic aliases | None (core generic standard is fully validated) |
| **HDFC Bank** | Netbanking / Corporate Statement export | **Level 2: Narration represented** | None | None | None | Narration grammar transcribed from published specimens (RTGS/NEFT prefixes, 40-char truncation) | UTR extraction from HDFC-style narration strings in synthetic data | Ingestion of native HDFC CSV/XLS exports (metadata headers, native column layouts) | Sanitized authentic HDFC statement export fixture + dedicated `hdfc_csv` adapter |
| **ICICI Bank** | Corporate Netbanking / NACH batch export | **Level 2: Narration represented** | None | None | None | Narration grammar transcribed from published specimens (ACH C/ batch tokens) | NACH/NEFT narration pattern parsing in synthetic benchmarks | Ingestion of native ICICI statement files (multi-header structure, balance columns) | Sanitized authentic ICICI statement export fixture + dedicated `icici_csv` adapter |
| **State Bank of India (SBI)** | SBI CBS / Netbanking export | **Level 2: Narration represented** | None | None | None | CBS narration grammar transcribed from published specimens (hyphen-delimited tokens, merchant tags) | SBI-style narration parsing and UTR recovery in synthetic benchmarks | Ingestion of native SBI statement files (branch metadata rows, native headers, date formats) | Sanitized authentic SBI statement export fixture + dedicated `sbi_csv` adapter |
| **Axis Bank** | Axis Corporate / Mobile statement | **Level 2: Narration represented** | None | None | None | Narration patterns transcribed from published specimens (sponsor IFSC `RATN0000088`, UPI handles) | Sponsor IFSC matching and UPI narration attribution in synthetic benchmarks | Ingestion of native Axis statement files (header layout, debit/credit notation) | Sanitized authentic Axis statement export fixture + dedicated `axis_csv` adapter |
| **Kotak Mahindra Bank** | Kotak Corporate Netbanking | **Level 2: Narration represented** | None | None | None | IMPS narration patterns transcribed from published specimens (mixed-case slash-delimited) | IMPS reference parsing and keyword handling in synthetic benchmarks | Ingestion of native Kotak statement files (metadata rows, description wrapping, column names) | Sanitized authentic Kotak statement export fixture + dedicated `kotak_csv` adapter |
| **RBL Bank** | RBL Bank / Razorpay Nodal Account | **Level 2: Narration represented** | None | None | None | Sponsor IFSC `RATN0000088` documented from Razorpay settlement specifications | Sponsor IFSC evidence weighting (`ifsc_ratn`) in Tier B attribution | Ingestion of native RBL statement export files | Sanitized authentic RBL statement export fixture + dedicated `rbl_csv` adapter |

---

## 3. Summary of Findings & Evidence Discipline

1. **Only Generic CSV is Registered in Production:**  
   `engine.bank_adapters.get_default_bank_adapters()` returns only `[GenericCsvBankAdapter]`. No named-bank adapter (`hdfc_csv`, `sbi_csv`, etc.) is registered in the production engine.
2. **Narration Representation vs. File Ingestion:**  
   Narration grammar rules (such as recognizing `RTGS/`, `NEFT CR-`, or IFSC `RATN0000088`) allow the engine to attribute credits from synthetic statements that mimic real bank text. They do **not** prove that Untangle can parse raw, un-normalized bank statement files from those institutions.
3. **Synthetic OOD Fixture Scope:**  
   `fixtures/bank_statement_ood.csv` is an out-of-distribution parser stress fixture covering generic header variations, accounting markers, and multiline quoting. It is not an authentic bank export and does not validate compatibility with named banks.
4. **Public Claim Policy:**  
   Untangle never claims multi-bank validation without authentic fixtures and dedicated, unambiguous adapters. All benchmark outputs explicitly state the generic/synthetic boundary.
