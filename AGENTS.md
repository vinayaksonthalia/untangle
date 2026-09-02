# Untangle contributor instructions

## Product boundary

Untangle is a precision-first, read-only finance controller for reconciliation. Monetary
calculations, attribution, reconciliation, journals, recovery decisions, and certificates must be
deterministic and independently verifiable.

Narration and other language-model output is advisory only. It must never establish evidence,
change money, override abstention, approve a journal, or certify a close. Prefer explicit
abstention or an actionable unsupported-input error over a guessed financial result.

## Evidence and claims

- Distinguish synthetic narration coverage from native bank/provider-format support.
- Add provider support or public claims only with authentic, sanitized evidence or authoritative
  documentation.
- Preserve provenance for decision-affecting adapters, rule packs, configuration, and schema
  versions.
- Bind decision-affecting configuration into canonical reports and certificates through explicit
  schema migrations.
- Never commit API keys, secrets, raw statements, private fixtures, generated financial inputs, or
  `out/` artifacts.

## Engineering rules

- Use integer paise for money. Reject booleans, non-finite values, contradictory debit/credit data,
  and ambiguous formats.
- Preserve existing public behavior unless a migration is explicitly documented.
- Avoid mutable process-global request configuration; pass resolved immutable configuration through
  the call graph.
- Preserve deterministic ordering, canonical serialization, replay identity, and exact resource
  ownership.
- Add regression coverage for corrected defects, including failure and abstention paths.

## Contribution workflow

- Keep changes focused and independently reviewable; avoid unrelated formatting or refactors.
- Do not include real financial data, credentials, signing keys, or personal data in commits,
  issues, or pull requests.
- State the exact verification commands and results in pull requests.
- Report suspected vulnerabilities according to `SECURITY.md`, not in a public issue.

## Verification

Run focused tests while developing, then the applicable repository checks before requesting review:

```bash
python -m pytest --cov --cov-report=term-missing
python -m coverage json
python scripts/branch_coverage_gate.py
python -m ruff check .
python -m ruff format --check .
```

Changes affecting attribution, reconciliation, certificates, or evaluation should also run the
applicable generator, sealed-holdout, and multi-month checks documented in the repository.
