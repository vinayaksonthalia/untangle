# Feature 004 — Adversarial Challenger & Proof-Margin Gate · STATUS / HANDOFF

_Last updated: 2026-08-27. Branch: `feat/adversarial-challenger` (not yet pushed / no PR yet)._

## Where we are
The intelligence roadmap is **#3 → #2 → #1** (see `memory/intelligence-roadmap.md`). We are mid-way
through **#3** (this feature). sol (gpt-5.6-sol via AgentRouter) is the design/review model — but its
**budget pool is exhausted (HTTP 402)**; top up AgentRouter before delegating to sol again.

## DONE (committed on `feat/adversarial-challenger`)
- **Spec-kit trail**: `spec.md`, `plan.md`, `research.md`, `data-model.md`, `contracts/challenger.md`,
  `checklists/requirements.md`, `tasks.md`. (commit `159a2ad`)
- **`engine/challenger.py`** — pure, deterministic. `challenge_razorpay(...)` returns a
  `ChallengerResult` with `proof_margin = rzp_score − best_competing_score`. Operators: observed
  competing rail + evidence ablations (drop_exact_identifier / drop_suffix / drop_amount_tie /
  drop_setsum / drop_time_proximity / unlinked_rzp). ≤16 cap, deterministic order, truncation⇒abstain.
- **Gate wired** into `engine/attribute.py` via `_finalize_razorpay(...)`, at BOTH Razorpay acceptance
  points in `attribute_line` (Tier A exact-UTR + final return). `margin_threshold` keyword (default
  **0.0 = challenger skipped = byte-identical to before**) on `attribute_line` and `attribute_all`.
- **Model**: added optional `proof_margin: float|None` and `competing_explanation: dict|None` to
  `RailAttribution`. (commit `fcf3f56`)
- **Tests** (commit `4349a9b`): `tests/unit/test_challenger.py` (8) + `tests/property/
  test_challenger_additive.py` (3). Full suite **129 green** (118 pre-existing + 11 new). Additivity and
  precision-monotonicity proven. ruff clean.

Verified behaviour: clean exact-UTR → large margin (accept); one real tie buried in brand/IFSC/
settlement_ref resemblance → small margin (fragile); a near-tie competing gateway → small margin.

## UPDATE 2026-08-27 (later) — calibration + README done; PR #17 open
- **Conformal calibration DONE** — `eval/margin_calibration.py` (Clopper-Pearson + Bonferroni +
  recall guard + fail-closed) with 9 unit tests. Honest run result: 95 Razorpay candidates, **0
  false-positives → precision already 1.000**, so no positive threshold certified; challenger stays
  **surface-only** (`margin_threshold=0.0`). Reported truthfully, not forced.
- **Professional README DONE** — house-style rewrite; Phase-5 README gate updated. Full suite **138 green**.
- **PR [#17](https://github.com/vinayaksonthalia/untangle/pull/17) open** (challenger + gate + calibration
  + tests + README). Qodo reviewing.
- **AgentRouter note:** premium pool (Opus/sol/GPT) is on a *batched daily quota* and currently exhausted
  (402, affecting everyone); DeepSeek/GLM work but are heavy reasoning models. Do the work directly; use
  workers only when they clearly help. Don't poll the premium pool or run concurrent duplicate calls
  (usage policy).

## STILL TO DO (after PR #17)
1. Gate the **split-reconstruction** acceptance path (second machine Razorpay path, design D3) — not done.
2. **Surface** `proof_margin` in proof packets + a dashboard exception line from the structured fields.
3. Then roadmap **#2 (active recovery controller)**, then **#1 (global solver)**.

## (historical) original resume notes
1. **Conformal calibration** — Add to `eval/calibration.py`:
   - `@dataclass(frozen=True) MarginCalibration{threshold, precision, precision_lower_bound,
     candidate_coverage, overall_coverage, razorpay_recall, accepted, errors}`.
   - `_clopper_pearson_upper(k, n, alpha)` — exact one-sided upper bound on the error rate via
     `math.comb` + binary search on the binomial CDF (handle k=0, k=n).
   - `collect_candidate_margins(threshold=0.55)` — build `lines`/`index` as `eval/sealed.py` does
     (`load_bank`, `load_recon`, `ReconIndex`); for each line `a = attribute_line(ln, index, 0.55,
     margin_threshold=0)`; if `a.rail=="razorpay_settlement" and not a.abstained` it's a candidate;
     `margin = challenge_razorpay(ln, index, a.evidence, narration_rail_signals(ln), a.confidence,
     _combine).proof_margin`; correctness from ground truth. Ground truth = `data/ground_truth.json`
     `["labels"]` (list of `{line_id, rail}`); map `ln.key → line_id` via
     `eval.metrics.build_key_to_lineid("data/bank_statement.csv")`.
   - `calibrate_proof_margin(candidates, total_lines, baseline_recall, *, target_precision=0.99,
     confidence=0.95, max_recall_drop=0.01, grid_step=0.005)` — grid 0..1; accept margin≥t; k=accepted
     wrong; Bonferroni `alpha=(1−confidence)/#gridpoints`; certify where `1−U ≥ target` AND
     `deployed_recall ≥ baseline−0.01` AND `≥0.90`; pick max candidate_coverage, tie-break lower t;
     **fail-closed** (return None ⇒ keep feature disabled) if none qualify.
   - Calibration unit tests: zero-accepted, zero-errors, one-error, insufficient sample, grid tie-break,
     Bonferroni, no-feasible-threshold fail-closed. (add `tests/unit/test_margin_calibration.py`)
2. **Run calibration** on the sealed holdout; confirm a certified threshold keeps **precision 1.000**
   and **recall ≥ 0.90**. Set that threshold in `engine/config.py` and thread it into the pipeline
   (`engine/cli.py`, `engine/service.py`, `eval/sealed.py` `attribute_all` calls) so the feature is
   actually ON in the product. If calibration fails closed, leave `margin_threshold=0.0` and say so.
3. **Split-reconstruction gate** — `reconstruct_splits` is a SECOND machine Razorpay acceptance path
   (design D3). Apply the same gate there so split legs are also challenged. Not yet done.
4. **Surfacing** — proof-packet `proof_margin` on accepted lines; structured `competing_explanation` on
   margin abstentions; a dashboard exception line generated from the structured fields (maybe a new
   reason label). Regenerate `ui/dashboard.html`.
5. **Docs + metric sweep** — README/DEMO/landing proof band if a metric changes; `docs/
   EXCEPTION_TAXONOMY.md`; run the full sweep; log any real defect in `INCIDENTS.md`.
6. **Ship** — full suite + ruff + bandit green; push branch; open PR; `/review` (Qodo); merge when
   clean. Then start **#2 (active recovery controller)**, then **#1 (global solver)**.

## Other open/known items
- **Deploy**: `render.yaml` + `Dockerfile` on `main`; user will deploy to **Render (free)** themselves
  (New → Blueprint → repo). Deploy + demo video are the LAST mile, after the product is complete.
- **All PRs #9–#16 merged** to `main` (proof-gate, split reconstruction, proof packets, ledger,
  hygiene/CI, baseline battle, deploy config, landing refinement). Working tree `main` is clean.
- Product framing: untangle is a **fully-functional product**, not a demo — real users upload their own
  three files; the sample is just an instant preview.
