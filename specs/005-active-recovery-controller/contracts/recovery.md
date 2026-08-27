# Contract: engine/recovery.py

```python
def diagnose(
    line: BankCreditLine,
    attribution: RailAttribution,
    index: ReconIndex,
    exception: ExceptionRecord | None,
) -> list[Hypothesis]
```
- Pure, deterministic. Reads only from its inputs.
- Returns competing hypotheses with `blocking_reason` derived from the credit's existing evidence
  (`razorpay_signals`, `narration_rail_signals`) and exception `reason_code`.
- Hypothesis `weight` comes from the existing `_combine` scoring (or the attribution's evidence
  weights). Never invents new signals.
- Never mutates `line`, `index`, `attribution`, or `exception`.

```python
def build_recovery_plan(
    lines: list[BankCreditLine],
    attributions: list[RailAttribution],
    index: ReconIndex,
    exceptions: list[ExceptionRecord],
    *,
    max_actions: int = 20,
) -> RecoveryPlan
```
- Pure, deterministic. Reads only from its inputs.
- For each unresolved credit (abstained or UNKNOWN attribution), calls `diagnose`, maps the
  `blocking_reason` to a `RecoveryAction` via the fixed taxonomy, groups identical actions,
  ranks by `gain_per_cost`, and caps at `max_actions`.
- `recoverable_if_actioned_paise` counts each credit at most once across all actions (set union).
- Amounts are upper bounds ("up to … if confirmed"), never claims of money owed.
- Never mutates any input.

```python
def resolve_delta(
    before_report: dict,
    after_report: dict,
) -> dict
```
- Pure, deterministic. Compares two serialized report dicts.
- Returns `{"newly_resolved": [...], "newly_reconciled": [...], "recovered_paise": int}`.
- Safe on identical inputs (returns empty delta).
- Never runs the pipeline; never mutates inputs.

## Caller-side contract (in `engine/cli.py` `build_report`)
- Called **after** exceptions are built, as a post-pipeline read-only pass.
- Attaches `recovery_plan` as a new top-level section of the report.
- Never alters attributions, reconciliations, fee-GST, or any other report section.
- The caller must not feed recovery outputs back into attribution or reconciliation.
