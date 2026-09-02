## Summary

<!-- What changed and why? Keep this PR focused on one outcome. -->

## Safety and compatibility

- [ ] No real financial data, credentials, API keys, or signing keys are included.
- [ ] Public schemas, APIs, and deterministic behavior are unchanged or documented.
- [ ] Financial claims are backed by tests or reproducible evidence.
- [ ] New failure paths fail closed and preserve explicit abstention.

## Verification

<!-- List the exact commands and results. -->

- [ ] Focused tests
- [ ] `python -m pytest`
- [ ] `python scripts/branch_coverage_gate.py`
- [ ] `python -m ruff check .`
- [ ] `python -m ruff format --check .`
