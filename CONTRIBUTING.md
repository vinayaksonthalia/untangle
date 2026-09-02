# Contributing to Untangle

Thank you for helping improve Untangle. Financial reconciliation code must favor correctness,
traceability, and explicit abstention over convenient but unsupported answers.

## Before opening a change

- Search existing issues and pull requests for overlapping work.
- Open an issue first for substantial behavior, schema, API, or architecture changes.
- Keep each pull request bounded to one independently reviewable outcome.
- Never commit real bank statements, merchant data, credentials, signing keys, or generated secrets.

## Development setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev,web,crypto,mcp]'
```

Run the relevant focused tests while developing, then run the repository gates before requesting
review:

```bash
python -m pytest
python scripts/branch_coverage_gate.py
python -m ruff check .
python -m ruff format --check .
```

Changes that affect attribution, reconciliation, certificates, or evaluation should also run the
applicable sealed-holdout and multi-month checks documented in the repository.

## Pull-request expectations

- Branch from the current `main` and avoid unrelated formatting or refactors.
- Add regression tests for every corrected defect and tests for failure paths.
- State what changed, why it is safe, and exactly which commands were run.
- Preserve deterministic outputs and fail-closed behavior unless the change explicitly revises a
  documented contract.
- Do not present synthetic or unlabeled results as production evidence.
- Update user-facing documentation when behavior, configuration, or public schemas change.

By intentionally submitting a contribution for inclusion in Untangle, you agree that it is provided
under the [Apache License 2.0](LICENSE), consistent with section 5 of that license, unless you clearly
mark it as "Not a Contribution."

Please follow the [Code of Conduct](CODE_OF_CONDUCT.md) in all project spaces. Report vulnerabilities
according to [SECURITY.md](SECURITY.md), not in a public issue.
