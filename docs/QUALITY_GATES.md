# Quality gates

The CI job runs the seeded fixture generation, the complete test suite, Ruff,
Bandit, and a branch-coverage gate. Coverage is measured across the source
packages (`engine`, `eval`, `generator`, `ui`, and `webapp`) with a 65% minimum.
The floor is intentionally evidence-based: the current generated seed-42 suite
reports 66.48% branch coverage (265 passed). It is a floor, not a quality score;
new behavior still needs focused tests.

Run locally after generating the fixtures:

```sh
python -m generator.generate --seed 42 --scale 1.0 --out data
python -m eval.sealed
python -m engine.cli run --bank data/bank_statement.csv \
  --recon data/recon_report.json --ledger data/order_ledger.csv \
  --out out/ --no-ai --seed 42
make coverage
```

Mutation testing is deliberately scoped to reconciliation, journal, and
recovery logic because those modules contain the accounting invariants. The
mutmut test selection is limited to fixture-independent reconciliation and
recovery unit tests, so it works from a clean checkout. It is an opt-in local
gate (`make mutation`) rather than a required PR check: mutmut can take
substantially longer than the normal suite. Install it separately with
`python -m pip install -e '.[quality]'`, then review surviving mutants rather
than treating a mutation score as proof of correctness.

The project does not add a broad static type checker in this change. The code
base is currently not annotated consistently enough for an honest strict mypy
gate without a large, unrelated annotation migration. Ruff remains required in
CI as the lightweight static correctness check.
