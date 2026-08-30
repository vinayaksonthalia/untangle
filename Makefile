# untangle — developer run targets (constitution V: clone-and-run in one command)
# Uses a local venv if present, else falls back to python3.
PY ?= $(shell [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)

BANK   ?= data/bank_statement.csv
RECON  ?= data/recon_report.json
LEDGER ?= data/order_ledger.csv
TRUTH  ?= data/ground_truth.json
OUT    ?= out/
SEED   ?= 42

.PHONY: help venv run eval ablation test coverage mutation lint why clean

help:
	@echo "make venv     - create .venv and install dev deps (pytest, hypothesis, ruff)"
	@echo "make run      - deterministic no-AI attribution -> out/report.json"
	@echo "make eval     - score out/report.json against blind ground truth"
	@echo "make ablation - eval with AI on/off delta + latency + cost/1k"
	@echo "make test     - run the full pytest suite"
	@echo "make coverage - run tests with the enforced 65% branch-coverage floor"
	@echo "make mutation - run targeted mutation testing for reconciliation/accounting"
	@echo "make lint     - ruff check"

venv:
	python3 -m venv .venv
	.venv/bin/python -m pip install -q --upgrade pip pytest hypothesis ruff

run:
	$(PY) -m engine.cli run --bank $(BANK) --recon $(RECON) --ledger $(LEDGER) \
	  --out $(OUT) --no-ai --seed $(SEED)

eval:
	$(PY) -m eval.harness --run $(OUT)report.json --truth $(TRUTH)

ablation:
	$(PY) -m eval.harness --run $(OUT)report.json --truth $(TRUTH) --ablation

why:
	$(PY) -m engine.cli why $(KEY) --out $(OUT)

test:
	$(PY) -m pytest

coverage:
	$(PY) -m pytest --cov --cov-report=term-missing --cov-fail-under=65

mutation:
	@$(PY) -c 'import mutmut' 2>/dev/null || (echo "Mutation tooling is optional. Install it with: $(PY) -m pip install -e \".[quality]\""; exit 1)
	$(PY) -m mutmut run
	$(PY) -m mutmut results

lint:
	$(PY) -m ruff check engine eval tests

clean:
	rm -rf out/ .pytest_cache __pycache__ */__pycache__ */*/__pycache__
