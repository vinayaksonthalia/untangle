#!/usr/bin/env python3
"""Enforce a BRANCH-coverage floor from coverage.py's JSON report.

``pytest --cov-fail-under`` checks coverage.py's *combined* statement+branch percentage, so a run
can pass that threshold while the branch-only rate sits below the number the quality gate promises.
This script isolates branches: it reads ``coverage.json`` (written by ``coverage json``) and fails
when ``covered_branches / num_branches`` is under the floor. CI and the local ``make coverage``
target both call it, so the enforced number is identical everywhere.
"""

from __future__ import annotations

import json
import sys

THRESHOLD = 65.0
_COVERAGE_JSON = "coverage.json"


def main() -> int:
    try:
        with open(_COVERAGE_JSON, encoding="utf-8") as fh:
            totals = json.load(fh)["totals"]
    except (OSError, ValueError, KeyError) as exc:
        print(f"branch-coverage gate: could not read {_COVERAGE_JSON} ({exc}). "
              "Run `coverage json` after the test run.", file=sys.stderr)
        return 2
    covered = totals.get("covered_branches", 0)
    total = totals.get("num_branches", 0)
    pct = 100.0 * covered / total if total else 100.0
    ok = pct >= THRESHOLD
    print(f"Branch coverage: {covered}/{total} = {pct:.2f}%  (floor {THRESHOLD:.0f}%)  "
          f"[{'OK' if ok else 'FAIL'}]")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
