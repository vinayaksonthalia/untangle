# Maximum-Payload End-to-End Stress & Resource Benchmark

This document defines Untangle's high-volume stress benchmark suite, resource measurement protocol, and verified input boundary contracts.

---

## 1. Overview & Commands

The benchmark suite exercises the complete Untangle reconciliation pipeline near its documented **15 MiB per-file input limit**:

$$\text{Ingest} \longrightarrow \text{Attribution} \longrightarrow \text{Solver / Reconciliation} \longrightarrow \text{Exceptions} \longrightarrow \text{Investigation} \longrightarrow \text{Journal / Certificate Output}$$

### Standard Commands

```bash
# Run CI-safe baseline profile (~1.4 MiB payload, <1s runtime):
python -m eval.benchmark --profile ci-safe

# Run near-limit stress profile (~14.5 MiB Recon JSON, ~16.0 MiB payload, ~8s runtime):
python -m eval.benchmark --profile near-limit

# Run near-limit stress profile with global constrained solver enabled:
python -m eval.benchmark --profile near-limit --global-solver

# Output machine-readable JSON:
python -m eval.benchmark --profile near-limit --json
```

---

## 2. Benchmark Profiles

| Profile | Scale | Recon Rows | Ledger Rows | Bank Lines | Recon Report Size | Total Payload | Typical Runtime | Typical Peak Heap | Target Environment |
|---|---|---|---|---|---|---|---|---|---|
| **`ci-safe`** | 0.15 | 1,902 | 1,676 | 273 | 1.27 MiB (1,327,558 B) | 1.42 MiB (1,492,732 B) | ~1.0 s | ~5.0 MiB | Automated CI & quick local regression |
| **`moderate`** | 0.50 | 6,244 | 5,582 | 288 | 4.23 MiB (4,435,900 B) | 4.70 MiB (4,929,480 B) | ~2.5 s | ~18.0 MiB | Intermediate load testing |
| **`near-limit`** | 1.75 | 21,724 | 19,644 | 291 | 14.48 MiB (15,179,810 B) | 16.00 MiB (16,779,350 B) | ~8.4 s | ~46.3 MiB | Maximum-payload boundary stress testing |

---

## 3. Dataset Construction & Provenance

Benchmark datasets are generated deterministically using `eval/benchmark_generator.py` (which leverages core generator primitives from `generator.build`, `generator.bank`, and `generator.noise`):
- **Deterministic & Seeded**: Same seed and scale produce byte-identical inputs.
- **Zero Real Financial Data**: All merchant names, customer emails, order identifiers, and bank account numbers are synthetic.
- **Realistic Exception Injections**: Retains full representative complexity including split settlements, value-date jitter, rounding drifts, mangled UTRs, on-hold rows, cross-cycle refunds, and decoy counterparties.
- **In-Memory & Ephemeral**: Benchmarks run in memory or using ephemeral temporary files without committing large generated files into Git history.

---

## 4. Input Boundary Contracts

Untangle enforces strict, fail-closed boundaries across all input surfaces:

| Surface / Channel | Constraint | Limit | Exceeded Behavior |
|---|---|---|---|
| **Service / CLI Snapshot** | Per-file size limit | `<= 15 MiB` (15,728,640 bytes) | Rejects with actionable `InputError` during lazy chunk reading |
| **Web Upload (`/reconcile`)** | Per-file size limit | `<= 15 MiB` (15,728,640 bytes) | Rejects with HTTP 413 (`<filename> is larger than 15 MB`) |
| **Web Upload (`/reconcile`)** | Aggregate request body | `<= 46 MiB` (48,234,496 bytes) | ASGI `BodySizeLimitMiddleware` returns HTTP 413 before app parsing |
| **Verify Endpoint (`/api/verify`)** | Certificate payload | `<= 512 KiB` (524,288 bytes) | Rejects with HTTP 413 |
| **Web Concurrency** | Semaphore pool | 2 active slots | Rejects over-capacity requests with HTTP 503 |
| **Reconciliation Timeout** | Execution wall time | 90.0 seconds | Aborts worker and returns HTTP 504 |

---

## 5. Measured Metrics & Meaning of Peak Heap

1. **Wall-clock Runtime**: End-to-end duration from raw input byte parsing to completed journal and verified close certificate.
2. **Peak Python Heap (`tracemalloc`)**:
   > [!NOTE]
   > Peak heap is measured using Python's standard `tracemalloc` module. It captures the peak memory allocated by Python objects on the interpreter heap during execution.
   > 
   > **What it does NOT measure**: It does not represent total operating system Resident Set Size (RSS), C-extension allocations, mmap buffers, shared libraries, or OS page-cache memory.

---

## 6. Mathematical & Structural Invariants Under Load

Every benchmark execution audits 7 non-negotiable invariants:
1. **1:1 Terminal Disposition**: Every bank statement line receives exactly one terminal attribution verdict.
2. **Attribution Conservation**: $\sum \text{Attributed Rails} + \text{Abstained (Unknown)} = \text{Total Bank Lines}$.
3. **Exact Paise Conservation**: Every reconciled credit matches its covering recon rows to the exact paise (within the labeled $\le ₹1$ rounding drift tolerance).
4. **Double-Entry Journal Balance**: Every generated Tally XML and JSON voucher balances exactly in paise ($\sum \text{Debit} = \sum \text{Credit}$).
5. **Zero Double-Covered Recon Rows**: No settlement row is claimed by more than one bank credit line.
6. **Period Close Certificate Validity**: Cryptographic digest and report binding verify successfully.
7. **Deterministic Replay**: Running on identical input bytes produces an identical `audit_root` and certificate hash.

---

## 7. Observed Local Run Results

*Measured on macOS (Apple Silicon arm64, Python 3.14.7, Seed 42)*:

### Near-Limit Benchmark Run Summary

```text
==============================================================================
  UNTANGLE PIPELINE STRESS BENCHMARK — Profile: NEAR-LIMIT
==============================================================================
  Timestamp (UTC)     : 2026-09-01T11:06:06.561820+00:00
  Platform / Python   : macOS-26.6.2-arm64-arm-64bit-Mach-O (Python 3.14.7)
  Scale / Seed        : 1.75 / 42
  Global Solver       : DISABLED (OFF - Baseline)
------------------------------------------------------------------------------
  INPUT METRICS:
    - Recon Report JSON : 15,179,810 bytes (14.48 MiB) · 21,724 rows
    - Order Ledger CSV  : 1,565,654 bytes (1.49 MiB) · 19,644 rows
    - Bank Statement CSV: 33,886 bytes (0.03 MiB) · 291 lines
    - Total Payload     : 16,779,350 bytes (16.00 MiB)
------------------------------------------------------------------------------
  RESOURCE & PERFORMANCE MEASUREMENTS:
    - Wall-clock Time   : 8.3970 s
    - Peak Python Heap  : 46.26 MiB (48,509,633 bytes)
      (Note: Measured with tracemalloc; represents Python heap allocations, not total process RSS)
------------------------------------------------------------------------------
  RECONCILIATION OUTPUT SUMMARY:
    - Total Attributed  : 291 lines (Razorpay: 96, Unknown: 0)
    - Reconciled Credits: 92 credits (₹52,250,894.64)
    - Unresolved Slice  : 4 credits
    - Recoverable ITC   : ₹76,765.45
    - Exceptions / Inv. : 32 items
    - Journal Vouchers  : 92 double-entry vouchers
    - Audit Root Hash   : ff92e29a80e78f08b245a38340f6eb22bb3265714cd83ccb8bb464188f27467a
------------------------------------------------------------------------------
  INVARIANT AUDIT:
    - 1:1 Terminal Verdicts     : PASS
    - Attribution Conservation  : PASS
    - Exact Paise Conservation  : PASS
    - Double-entry Journal Bal. : PASS
    - Zero Double-Covered Rows  : PASS
    - Close Certificate Valid   : PASS
    - Determinism on Rerun      : PASS
------------------------------------------------------------------------------
  OVERALL RESULT: [PASS] All performance & correctness invariants held under load.
==============================================================================
```

---

## 8. Limitations & Scope Boundary

- **Synthetic Load Benchmark**: This benchmark validates memory boundedness, algorithmic scaling, and mathematical correctness under high-volume synthetic load. It does not establish universal real-world bank format compatibility (see [BANK_FORMAT_EVIDENCE.md](BANK_FORMAT_EVIDENCE.md)).
- **Hardware Variation**: Execution runtimes vary across CPU architectures and memory bandwidth; CI tests use invariant checks and allocation ceilings rather than fragile wall-clock assertions.

---

## 9. Concurrent Saturation & Resource Cleanup

Untangle's web reconciliation endpoints (`/reconcile` and `/api/reconcile`) are verified against concurrent saturation via `tests/integration/test_concurrent_saturation.py`:

- **Bounded Worker Pool**: Concurrency is hard-capped at 2 simultaneous reconciliation workers (`_RECONCILE_SLOTS = 2`). Excess concurrent requests receive HTTP 503 without entering worker functions.
- **Early Admission**: Requests exceeding capacity are turned away before creating temporary directories or writing uploaded files to disk.
- **Exact Slot Retention**: A worker thread that times out from the caller's perspective continues holding its concurrency slot until background execution truly finishes, preventing worker queue explosion.
- **Immediate Resource Deletion**: Temporary directories and uploaded files are deleted across all terminal outcomes (success, 413, 422, 500, 503, 504).
- **Snapshot Isolation**: Admitted workers execute over immutable in-memory byte buffers (`reconcile_bytes`), ensuring concurrent requests operate with zero state or pathname contamination.
